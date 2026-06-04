# Project Context And Progress

Last updated: 2026-06-04

## Operating Rule

This file is the compact project operating brief, not an append-only diary. Keep it current, prune stale history every pass, and keep it small enough for reliable Codex continuity.

- Target size: under 600 lines.
- Prefer current truth over historical detail.
- Move detailed reports to dated docs when needed; do not paste long logs here.
- Long-form fallback: `docs/OVERALL_CONTEXT.md`.
- Every build pass must update progress, blockers, completed work, and running notes if they changed.

## Project Goal

Build CML, a local-first downloadable desktop app for personal context management.

The user creates a local vault, adds files, folders, links, notes, screenshots, chat transcripts, and other memory artifacts, then CML clusters related material, indexes it, trains verified local cluster experts, and supplies structured context to local or external tools through the app, Bridge, CLI, and API.

Target user: general second-brain users, not only developers.

Public V1 target: end of July 2026 as a Windows-only public release. There is no private-demo fallback path; release slips until public-quality gates pass, including a working, high-quality verified LoRA cluster expert function.

## Current Product Decisions

- Product form: local downloadable desktop app, not a web app.
- Public V1 platform: Windows only.
- Release stance: public release only; no private alpha/demo fallback. If verified LoRA or other public gates fail, delay release rather than ship a demo.
- Desktop shell: Electron in `apps/desktop`.
- Backend: FastAPI in `backend`.
- V1 vault scope: explicit vault mode only; no full-device silent scanning.
- V1 storage: local vault folder with `CML_DATA_DIR=<vault>/.vault` and `CML_DATABASE_PATH=<vault>/.vault/cml.sqlite3`.
- V1 integrations: local synced folders first, including Google Drive Desktop, Dropbox, OneDrive, iCloud Drive, Obsidian folders, and normal folders.
- Later integrations: OAuth/API connectors after local ingestion is stable.
- UI direction: memory-board landing, visual map, chat workspace, Mindly-like organization, Obsidian-like graph/map; detailed UI rules live in `docs/UI_ARCHITECTURE.md`.
- UI responsive scope: no dedicated mobile screen for public V1; dark version and minimized/narrow desktop window version are required.
- UI reference folder: preserve `UI-ref/`; do not delete or refactor it.
- Cluster experts: compulsory product pillar.
- Public V1 expert claim: only say a cluster expert is trained after verified LoRA adapter graduation passes for that cluster.
- Local-first privacy: user data stays local unless the user explicitly exports or connects a tool.
- External access: Context Bridge through MCP, local HTTP API, CLI, and copy/export.

## Model And Runtime Decisions

Do not bundle LLM weights in the first installer. First-run setup should let users download CML-managed local models or connect existing local runtimes. Model choice must be recommended from the user's actual system conditions, not one default that assumes a high-end machine.

| Role | Default / Option | ID | Repo | Approx size | Target RAM |
| --- | --- | --- | --- | --- | --- |
| Default synthesis | Qwen3 4B Q4_K_M | `qwen3-4b-q4_k_m` | `Qwen/Qwen3-4B-GGUF` | ~2.5 GB | 8+ GB |
| Low-spec fallback | Phi-4 Mini Instruct Q4_K_M | `phi-4-mini-instruct-q4_k_m` | `unsloth/Phi-4-mini-instruct-GGUF` | ~2.5 GB | 8+ GB |
| Quality option | Qwen3 8B Q4_K_M | `qwen3-8b-q4_k_m` | `Qwen/Qwen3-8B-GGUF` | ~4.8 GB | 16+ GB |
| Optional later | Gemma 3 4B IT Q4_K_M | `gemma-3-4b-it-q4_k_m` | `Aldaris/gemma-3-4b-it-Q4_K_M-GGUF` | ~2.5 GB | 8+ GB |
| Optional later | Gemma 3 12B IT Q4_K_M | `gemma-3-12b-it-q4_k_m` | `nocturne23/gemma-3-12b-it-Q4_K_M-GGUF` | ~6.9 GB | 24+ GB |

Required recommendation system:

- Detect RAM, CPU threads, OS, architecture, AVX2, GPU/CUDA availability where possible, free disk, and currently configured local runtime.
- Recommend a low-spec, standard, or quality model tier with plain-language reasoning.
- Never recommend a model that is likely to make the app unusable on the current machine.
- Offer `Connect existing runtime` for users who already run Ollama, llama.cpp, LM Studio, or another OpenAI-compatible local endpoint.
- Keep retrieval/context-only mode available as an explicit degraded state, but not as the desired public V1 experience.
- Treat LoRA training requirements separately from synthesis model selection; expert training may need stricter hardware guidance than normal chat.

Runtime boundary:

- Use an OpenAI-compatible local runtime endpoint where possible.
- Support llama.cpp via `llama-server`.
- Support Ollama only when OpenAI-compatible behavior is confirmed.
- If no synthesis runtime is configured, use explicit degraded/context-only responses; do not silently pretend local chat works.
- Cluster experts are separate from the general synthesis model.
- Hash embeddings are development-only. Public/product setup must require a real local embedding backend or explicit degraded mode.

## Phase Progress

| Phase | Status | Progress | Remaining gate |
| --- | --- | --- | --- |
| Product definition | In progress | `[##########] 99%` | Windows-only public release decision record |
| UI prototype cleanup | In progress | `[##########] 99%` | Dark QA, minimized/narrow desktop QA, packaged-flow polish |
| Desktop app foundation | In progress | `[##########] 98%` | Clean VM launch validation and broader startup repair QA |
| Local backend foundation | Complete for current scope | `[##########] 100%` | Future service-layer cleanup only |
| Vault ingestion | Complete for current scope | `[##########] 100%` | Clean VM confirmation only |
| Embeddings and clustering | In progress | `[##########] 99%` | Broader threshold tuning on real user vaults |
| Chat/context routing | In progress | `[##########] 96%` | Complete-scope map/reduce, token budgets, runtime failure UX |
| Compulsory cluster experts | In progress | `[#########-] 85%` | Real machine validation still required for LLaMA Factory smoke, live adapter prompt run, and live quality benchmark |
| Context Bridge | In progress | `[#########-] 94%` | Capture UX polish and later external-client smoke |
| Packaging/install | In progress | `[##########] 98%` | Clean VM validation |
| QA/hardening | In progress | `[##########] 99%` | Clean VM package validation and larger user-owned vault benchmarks |

## Current Critical Path

- Execute clean Windows VM validation against the 2026-06-04 package: no dev Python, no Node, no preinstalled OCR, cold first-run.
- Keep Windows-only public V1 criteria. If verified LoRA or other public gates fail, delay release; do not ship a private demo fallback.
- Verify real adapter training and runtime loading before any broad "trained expert" claim.
- Compulsory expert work now has stricter dataset/diversity/quality gates, evaluation harness, smoke scripts, and Expert tab visibility, but still needs a real trainer command/model path before public claims.
- Build hardware-aware model recommendation so low-spec users receive safe model/runtime choices instead of high-end defaults.
- Keep the written threat model current and treat local API/Bridge auth regressions as release blockers.
- Continue retrieval threshold tuning beyond the benchmark harness using larger user-owned vaults.
- Defer Claude Desktop-specific Bridge smoke for now; Codex-style MCP smoke remains a local protocol check, and external-client claims stay conservative.
- Keep project context concise enough for session continuity.

## Phase Snapshot

Product definition:

- Done: PRDs, local-first product boundary, public V1 quality bar, public-only release stance.
- Remaining: Windows-only public V1 decision record, installer/update policy.

UI prototype cleanup:

- Done: main desktop surfaces, generated-reference alignment, backend-first data loading for core areas.
- Remaining: no new UI work now unless requested; later dark version, minimized/narrow desktop, packaged visual QA.

Desktop app foundation:

- Done: Electron workspace, backend launch/token seams, authenticated backend identity probe, vault lock override flow, file picker/open/reveal IPC, packaged pre-vault launch smoke, packaged main-process runtime logging.
- Remaining: clean VM smoke and broader packaged startup repair QA.

Local backend foundation:

- Done: FastAPI core, SQLite schema, fail-closed local API auth, authenticated backend identity endpoint, FastAPI lifespan migration, atomic job claiming, diagnostics, startup repair summary, vector maintenance endpoints, storage accounting, interrupted-migration repair signal.
- Remaining: future service-layer cleanup and continued recovery drills as schema changes.

Vault ingestion:

- Done: files, folders, links, text, Markdown/Obsidian metadata, PDFs, images, OCR runtime health, OCR jobs, per-page OCR job progress, page/chunk storage, dynamic-link fallback, packaged generated image/PDF OCR smoke, packaged dynamic-link/browser-runtime smoke.
- Remaining: clean VM confirmation only.

Embeddings and clustering:

- Done: default real embedding direction, hash dev fallback boundary, vector repair/compaction/policy endpoints, startup reconciliation, BM25 plus embedding scoring ledger, source-class weighting, threshold benchmark harness, retrieval eval fixtures, real T-drive cancellation smoke, 100-source benchmark script/report export, active-index transition smoke, real second-embedding cache smoke, user-shaped vault benchmark export, 1k benchmark script with timing targets, watched-folder back-pressure limits, cluster merge artifacts and rollback.
- Remaining: broader threshold tuning on user-owned vaults.

Chat/context routing:

- Done: LLM-first routing, retrieval intent, degraded runtime states, citation snapshots, attachment ingestion, coverage ledger, expanded-analysis foundation, chat message pagination, retrieval snapshot compaction, query/evidence cache pruning, evidence retention policy/enforcement API.
- Remaining: real complete-scope map/reduce, partial-failure classification, token budgets, runtime failure UX.

Compulsory cluster experts:

- Done: verified-LoRA contract scaffold, dataset export with source/token/diversity counts, duplicate-ratio gate, artifact schema, metrics, activation, rollback, delete guardrails, shell-free trainer process boundary, Windows-path trainer tests, stricter graduation contract, adapter config/weight validation, runtime-load plan metadata, deterministic expert evaluation harness, retrieval-vs-adapter delta gate, stale-adapter detection, Expert tab status UI, and repeatable LoRA expert/runtime smoke scripts.
- Remaining: execute the new Transformers/PEFT runtime smoke on a real machine with an installed local base model, record a real LLaMA Factory trainer run against that model, expand hardware matrix/time estimates, and replace deterministic adapter scoring with a live adapter-backed quality benchmark.

Context Bridge:

- Done: bridge tokens, permissions, token rotation, stale allowlist pruning, no-active-vault errors, notification behavior, constant-time token compare, explicit external-turn/artifact capture tools with vault/cluster permission checks, Codex-style MCP JSON-RPC smoke, malformed-client hardening.
- Remaining: full extension package, capture UX polish, later external-client smoke when reprioritized.

Packaging/install:

- Done: Windows package scripts, contributor requirements, OCR runtime staging script, local staged OCR runtime, valid rebuilt NSIS installer, silent install/uninstall smoke, packaged OCR verification, packaged model/embedding setup smoke, clean-machine validation script, generated-OCR full-vault packaged smoke, packaged dynamic-link/browser-runtime smoke, packaged interrupted-migration drill, packaged app launch smoke, AGPL-compatible Ghostscript release policy.
- Remaining: clean VM execution.

QA/hardening:

- Done: broad backend regression coverage, atomic job concurrency tests, local API auth/identity tests, OCR benchmarks, audits, diagnostic redaction/log-rotation policy, backend benchmark scripts, disposable-vault delete cleanup tests, failed embedding-write retry test, dynamic-link browser-runtime smoke with Playwright on `T:`, Codex-style MCP smoke, real second-embedding model/cache smoke, repeatable packaging/security smoke scripts, npm and Python vulnerability audits, threat model, 1k benchmark harness, startup stale-phase validation tests, recovery drills endpoint, first-run readiness gate tests.
- Remaining: larger user-owned vault benchmarks, clean VM package validation, hardware-aware model recommendation QA.

## Public V1 Blockers

These are release gates, not polish.

- Vault data path correctness: backend data and database must live under the selected vault folder in full-vault mode.
- Pre-vault/full-vault lifecycle: restricted pre-vault backend must block vault/source/chat/search/bridge data routes until a vault is selected.
- Startup repair: packaged pre-vault launch reaches ready and packaged migration drill passes; visible repair UI still needs broader clean-VM/package QA.
- Migration durability: schema versioning exists, but interruption/recovery tests and real migration scripts must mature as schema changes continue.
- Disk preflight: installer/model/OCR/indexing/ingestion flows need required/available space checks.
- Local API auth: Electron-managed private APIs now fail closed without the local API token; renderer-origin validation and Bridge-token separation remain release gates.
- Auth threat model: written in `docs/THREAT_MODEL.md`; keep it updated and enforce it through release-gate tests before public V1.
- Embedding setup gate: production cannot silently use hash embeddings; semantic features must block/degrade explicitly when embeddings are unavailable.
- Model integrity: managed model downloads record SHA-256 and verify real pinned expected hashes from `docs/model-integrity-manifest.json`.
- Scheduler synthesis gate: background jobs that should not run during generation must respect active/retriable generation states.
- Chat recovery: interrupted generations need durable timeline placeholders, retry actions, and no fake assistant messages.
- Complete analysis: current broad rerun is `expanded_analysis`; reserve `complete_analysis` for future evidence-packet map/reduce and return `501` if requested before implementation.
- Deletion graph: deleted sensitive content must disappear from retrieval/search immediately before async cleanup.
- Diagnostics: log rotation policy exists and full-vault unpacked package smoke covers diagnostics export; clean VM execution remains.
- MCP Bridge: Codex-style JSON-RPC smoke passed; keep external-client readiness claims conservative while Claude Desktop-specific smoke is deferred.
- LoRA: public V1 requires verified real adapter training, adapter artifact validation, runtime load against a real local model, rollback, supported hardware, failure codes, and quality win over retrieval baseline.
- LoRA graduation framing: small or insufficient clusters should remain retrieval-backed with explicit status instead of pretending every cluster can graduate.
- Model recommendation: public V1 must recommend safe synthesis/embedding/expert setup by detected system tier, because many users will not have high-end hardware.
- OCR/package: packaged OCR runtime, generated OCR fixture smoke, dynamic-link smoke, migration drill, and installer smoke pass; Ghostscript path is AGPL-compatible public release.

## Next Backend Build Steps

Scope constraints for this list: compulsory cluster expert group only; no package rebuild unless explicitly requested.

1. Run `scripts/backend/smoke-lora-expert.ps1` without `-AllowTestTrainer` using a real `CML_LORA_TRAINER_COMMAND` and record command, base model, dataset hash, and adapter path.
2. Run `scripts/backend/smoke-lora-runtime.ps1` against the adapter and live local inference runtime; fail public expert claims until the runtime is reachable and adapter load contract passes.
3. Replace deterministic adapter-score proxy with a live adapter-backed generation benchmark once the runtime can attach adapters.
4. Add benchmark report export for strict categories: factual recall, summarization, citation grounding, contradiction handling, style transfer, and out-of-scope refusal.
5. Expand hardware support reporting with estimated training time/cost, GPU/CPU mode, unsupported reasons, and safe retrieval-only fallback.
6. Add source-change threshold controls for staleness policy beyond dataset-hash mismatch and test source edits/deletions explicitly.
7. Harden rollback failure cases where the prior adapter path disappears or becomes invalid after training failure.
8. Add route/API tests for every typed failure code: trainer missing, trainer failed, adapter invalid, quality gate failed, runtime load failed, dataset changed, and hardware unsupported.
9. Add Expert tab actions for retrain, pause, activate, rollback, and delete while preserving the current honest status copy.
10. Update release docs with real smoke/benchmark results and exact public-V1 expert claim rules.

## Current Open Work

- Add written public V1 decision record: Windows-only; public release only; release slips until verified LoRA and other public gates pass.
- Finish first-run setup UI around the new readiness gate: vault path, model setup, embedding setup, OCR readiness, startup repair states.
- Make onboarding honest about local model/embedding download size, time, hardware requirements, and external Bridge privacy tradeoffs.
- Build model recommendation system based on detected system specs: RAM, CPU, GPU/CUDA, disk, runtime availability, and low/mid/high-spec user tiers.
- Add one-click local model/embedding dependency install or connect-existing-runtime flows.
- Add model provenance display in setup/settings using `/api/v1/models/integrity-manifest`.
- Continue backend service-layer extraction around raw route/database operations.
- Add complete-scope answering in stages: coverage ledger, BM25/embedding scoring, threshold tuning, map packets, reduce/synthesis, cache pruning.
- Finish local synced-folder import history and watched refresh polish where gaps remain.
- Build actual browser extension package and safer pairing flow.
- Execute the clean-machine package script and smoke sequence on a fresh Windows VM before public release claims.
- Keep Python dependency CVE auditing in repeatable contributor QA.
- Continue LoRA readiness gates now that expert work is active: real trainer smoke, live runtime load, live adapter benchmark, hardware matrix, rollback edge cases, and Expert tab controls.

## Recent Completed Work

- Continued the compulsory cluster expert build pass: added unique-source and duplicate-ratio dataset gates, minimum quality-delta config, deterministic expert evaluation harness, repeatable LoRA expert/runtime smoke scripts, strict LoRA MVP policy doc, and a backend-backed cluster Expert tab.
- Started the compulsory cluster expert build pass: added stricter LoRA graduation gates for source count, estimated token count, validation records, adapter validation, runtime-load contract metadata, stale active-adapter detection, richer failure codes, and `/api/v1/clusters/{cluster_id}/expert/status`.
- Updated cluster expert UI status mapping so backend states render as `Searchable now`, `Learning`, `Ready`, `Needs update`, or `Issue` instead of falling back to `Setting up`.
- Expert validation for this pass: focused backend/source tests ran 102 OK with 1 skipped; full backend discovery ran 178 OK with 1 skipped; `ruff check backend` passed; `npm run lint` passed with existing warnings only; `npm run build` passed.
- Added `docs/UI_ARCHITECTURE.md` as the detailed UI source of truth covering visual style, color tokens, tab requirements, component contracts, cross-cutting states, accessibility, responsive desktop behavior, and public V1 UI gates.
- Completed the full post-review implementation pass: atomic background job claiming, concurrent `/jobs/run-once` tests, fail-closed local API auth, authenticated backend identity handshake for Electron/frontend probes, FastAPI lifespan migration, shell-free LoRA trainer execution, Windows-path trainer tests, Ruff cleanup, split desktop lint scope, and packaged Windows validation.
- Current package artifacts: `apps/desktop/release/win-unpacked` and `apps/desktop/release/CML-0.1.0-Setup.exe` are valid local artifacts from the 2026-06-04 rebuild.
- Verification for this pass: full backend discovery ran 175 tests OK with 1 skipped; Electron behavior tests ran 8 OK; Electron token-store tests ran 4 OK; `ruff check backend` passed; `npm run lint` passed with existing warnings only; `npm run build` passed; `scripts/packaging/package-windows.ps1` passed; packaged runtime, clean-machine structure, full-vault OCR, dynamic-link, migration-drill, and app-launch smokes passed against `apps/desktop/release/win-unpacked`.
- Completed the non-Claude remainder of the current 10-step build list without touching LoRA: valid NSIS rebuild, generated OCR package smoke, packaged dynamic-link/browser runtime, real GGUF SHA-256 manifest pins, user-owned retrieval benchmark harness, Settings evidence-retention controls, update/migration policy, packaged interrupted-migration drill, AGPL-compatible Ghostscript policy, clean-machine validator hardening, and package/security verification.
- Previous tiny `.partial` setup files remain explicitly non-distributable.
- Verification for this pass: focused backend module ran 60 tests OK; frontend `npm run build` passed; package rebuild completed; full-vault packaged smoke generated and OCR-ingested image/PDF fixtures; packaged dynamic-link smoke reported browser runtime available; packaged migration drill reported interrupted migration; clean-machine validator passed on dev machine; packaged app launch passed; installer install/uninstall smoke passed after hardening async uninstall wait; `scripts/security/audit-app.ps1` passed npm audit, pip check, pip-audit, Electron behavior tests, token tests, and focused backend security tests.
- Completed the non-Claude remainder of the latest 10-step list without touching LoRA: clean-machine validator enhancement, full-vault packaged smoke execution, trusted model integrity manifest ingestion, cluster merge rollback, 1k benchmark timing targets, chat evidence retention APIs, startup recovery drill API, and first-run readiness gate.
- Packaged smoke result: refreshed `apps/desktop/release/win-unpacked` contains the current backend and `scripts/packaging/smoke-packaged-full-vault.ps1` passed against it: vault creation, text ingestion, reindex, semantic search, query-cache prune, startup phase validation, and diagnostics export. OCR fixture support is wired but no OCR fixture paths were provided.
- Packaging caveat: `scripts/packaging/package-windows.ps1 -SkipOcrRuntimeDownload` exceeded the 15-minute timeout after refreshing `win-unpacked`; it left invalid small NSIS artifacts, which were moved to `.partial`, and the stale blockmap was moved to `.stale`.
- Fixed packaged startup phase fallback: Python now has a full fallback startup phase vocabulary when `shared/startup-phases.json` is not packaged.
- Verification for this pass: focused backend module ran 60 tests OK; full backend discovery ran 170 tests OK with 1 skipped; `python -m compileall backend/app` passed; PowerShell parser validation passed; small retrieval benchmark smoke passed; clean-machine package validation passed on dev machine but detected Python/Node on PATH, so clean VM remains required.
- Completed backend steps 1, 2, 4, 5, 6, 8, 9, and 10 from the last list while explicitly skipping step 3 per user instruction: threat model, model SHA-256 integrity, clean-machine package validation, full-vault packaged smoke script, startup phase validation/staleness, 1k benchmark and watched-folder back-pressure, cluster merge artifacts/policy, and query/evidence cache pruning.
- Added `docs/THREAT_MODEL.md` and `docs/CLUSTER_MERGE_POLICY.md`.
- Added `scripts/packaging/validate-clean-machine-package.ps1`; rerun against `apps/desktop/release/win-unpacked` passed all checks after matching the real packaged OCR layout at `resources/backend/bin/ocr/manifest.json`.
- Added `scripts/packaging/smoke-packaged-full-vault.ps1` and `scripts/backend/benchmark-1k-vault.ps1`; PowerShell parser validation passed.
- Added backend support for local model integrity status/manifests, startup phase registry validation and stale timeout reporting, cluster merge artifact persistence/readback, watched-folder back-pressure reporting, and query/evidence cache pruning.
- Verification for this pass: focused backend unittest module ran 56 tests OK; full backend unittest discovery ran 166 tests OK with 1 skipped; `python -m compileall backend/app` passed.
- Added `docs/DEVILS_ADVOCATE_RESPONSES_2026-06-03.md` from the 100-question senior review, excluding Q100 as a decision driver per user instruction.
- Converted the useful review conclusions into release-risk gates: verified LoRA, clean-machine package, written threat model, model integrity, full-vault repair drills, scale benchmarks, and honest onboarding.
- Completed rebuild-dependent package work: rebuilt Windows NSIS package `apps/desktop/release/CML-0.1.0-Setup.exe`, added repeatable package smoke scripts, and verified silent install/uninstall.
- Packaged launch result: `scripts/packaging/smoke-packaged-app-launch.ps1` launched `win-unpacked\CML.exe`, cleared inherited `ELECTRON_RUN_AS_NODE`, and verified packaged pre-vault startup reached `ready`.
- Packaged runtime result: `scripts/packaging/smoke-packaged-runtime.ps1` verified packaged Python backend health, local API token enforcement, pre-vault route blocking, arbitrary CORS-origin rejection, model setup endpoints, embedding cache configuration, and production hash-embedding rejection.
- Packaged OCR result: packaged runtime resolved Tesseract, Ghostscript, and qpdf from `win-unpacked\resources\backend\bin\ocr`; image OCR and PDF OCR were available with `ocrmypdf`.
- Security result: added `scripts/security/audit-app.ps1`; `npm audit --audit-level=moderate` found 0 vulnerabilities, `pip-audit` found no known third-party vulnerabilities, Electron token/external URL tests passed, and full backend unittest discovery ran 160 tests with 1 skipped.
- Completed the requested 10 backend steps without LoRA, package rebuilds, or full UI rebuilds: user-shaped retrieval benchmark, real second-embedding cache smoke, query/evidence cache invalidation, dynamic-link browser smoke, Codex-style MCP capture smoke first, malformed MCP hardening, extension pairing/audit state, chat pagination/snapshot compaction, source-class calibration coverage, and initial service-layer extraction.
- Codex app MCP-first result: `scripts/backend/smoke-codex-mcp.ps1` passed JSON-RPC tool listing, `get_context`, `log_external_turn`, `capture_external_artifact`, and malformed-call rejection through the Codex-style MCP path.
- Runtime smoke result: Playwright Chromium was installed to `T:\CML-playwright-browsers`; dynamic-link smoke against `https://example.com/` reported browser runtime available and dynamic render completed.
- Embedding smoke result: real `sentence-transformers/all-MiniLM-L6-v2` and `sentence-transformers/paraphrase-MiniLM-L3-v2` caches were used under `T:\CML-embedding-index-smoke`; active index switched to the second model.
- Retrieval benchmark result: 100-source user-shaped vault benchmark exported JSON and Markdown reports under `T:\CML-build-smoke\user-shaped-retrieval\benchmark-reports`.
- Verification for this pass: full backend unittest discovery ran 160 tests with 1 skipped; `python -m compileall backend/app`, `python -m pip check`, `git diff --check`, and LoRA/training-file scope checks passed.
- Completed the next 10 backend steps without LoRA or rebuild work: real T-drive model/embedding cancellation smoke, 100-source retrieval benchmark/report export, source-class weighting, `compare_source_classes`, MCP external-turn/artifact capture, capture permission checks, active-index transition smoke, failed embedding-write retry coverage, expanded storage accounting, and benchmark scripts.
- Real download smoke result: embedding path reached `downloading` on `T:\CML-download-smoke` and cancelled cleanly; model path reached `downloading`, wrote 10 MB to `T:\CML-download-smoke\models`, reported 0.42% progress, and cancellation was observed.
- Retrieval smoke result: 100-source benchmark produced JSON and Markdown reports under `T:\CML-build-smoke\retrieval\benchmark-reports`; active-index transition smoke reported atomic activation observed.
- Verified this pass with focused `backend.tests.test_system_vault_lock_and_embeddings`: 46 run, all passed; full backend unittest discovery: 155 run, 1 skipped; `python -m compileall backend/app` passed.
- Completed backend build pass without LoRA, package rebuilds, or full UI rebuilds: BM25 plus embedding scoring ledger, threshold benchmark harness, retrieval eval fixtures, dynamic-link quality diagnostics, per-page OCR job progress, diagnostic log-rotation policy, interrupted-migration startup repair signal, storage accounting endpoint, disposable-vault delete cleanup tests, and download-cancel smoke script.
- Verified the backend pass with focused `backend.tests.test_system_vault_lock_and_embeddings` tests: 41 run, all passed; full backend unittest discovery: 150 run, 1 skipped; `python -m compileall backend/app` passed.
- Pruned `PROJECT_CONTEXT.md` into this compact operating brief to reduce context-window drift.
- Completed non-LoRA backend hardening: normalized download progress fields, vector maintenance helpers/endpoints, startup repair summary, richer diagnostics, link diagnostics, URL/IP hardening, Bridge token compare hardening, backend benchmark script, and regression coverage.
- Verified non-LoRA backend hardening with full backend tests: 143 tests run, 1 skipped; backend benchmark smoke covered 25 sources.
- Completed OCR/package-readiness sprint: staged local Tesseract, tessdata, qpdf, and Ghostscript; verified backend OCR runtime status; added OCR staging/package flags and benchmark script.
- OCR benchmark state: generated scanned `PROJECT_CONTEXT` full OCRmyPDF run reached 0.9769 sequence similarity, 0.9840 word recall, 0.9880 word precision; public sample showed high word recall/precision but low sequence similarity due reading-order differences.
- Completed vault ingestion core: local files/folders, Markdown/Obsidian metadata, folder refresh/reconcile, deletion graph cleanup, OCR job runner, page/chunk storage, and dynamic-link fallback.
- Completed chat/context foundations: LLM-first routing, retrieval intent, degraded runtime states, retrieval snapshots, attachments, transcript guardrails, coverage ledger, and `expanded_analysis` foundation.
- Completed verified-LoRA foundation scaffold earlier: contract, dataset export, trainer boundary, artifact schema, metrics, activation, rollback, guardrails, and tests. Real trainer/runtime smoke remains.
- Completed repository hygiene pass: removed stale tracked prototype copy and generated artifacts while preserving contributor dependency environments and `UI-ref/`.
- Added contributor reproducibility files under `requirements/` and the rule that dependency changes must update those files.

## Running Notes

- Public V1 is Windows-only and public-release-only. If it is not public-quality, delay release; do not rename it private alpha/demo.
- Public V1 selling point is verified, high-quality LoRA cluster experts; release requires this to work well.
- Model setup must be hardware-aware. Low-spec users need safe recommendations, not default high-end model assumptions.
- Q100 from the devil's advocate review is non-actionable per user instruction; do not use it to drive project decisions.
- User-facing "trained expert" language is allowed only after real adapter graduation.
- No package rebuild work unless explicitly requested; the latest requested rebuild was completed on 2026-06-04 and passed packaged smoke gates on this machine.
- No UI implementation unless explicitly requested; dark version and minimized/narrow desktop version are noted future requirements.
- Do not delete or alter `UI-ref/`.
- Playwright browser runtime for local dynamic-link smoke is installed on `T:\CML-playwright-browsers`; the packaged app now also stages `resources/ms-playwright`; contributor backend requirements include `playwright==1.60.0`.
- Packaging smoke scripts clear inherited `ELECTRON_RUN_AS_NODE`; otherwise packaged Electron launches in Node mode and will not execute app startup.
- Hash embeddings are development-only and must not be a silent production fallback.
- SQLite is authoritative; vector indexes are derived and rebuildable.
- Deleted sources must be excluded at SQLite/filter layer immediately, before async vector cleanup.
- Startup order: vault ownership, SQLite integrity/schema/migrations, job recovery, vector/index reconciliation, runtime detection, then API/UI traffic.
- `complete_analysis` is reserved for future map/reduce. Current broad path is `expanded_analysis`.
- MCP Bridge must not respond to JSON-RPC notifications.
- MCP Bridge must return explicit app errors like `1001 no_active_vault`; never silently choose the first vault.
- MCP cannot automatically see outside model responses; external transcripts are capturable only when the MCP client explicitly sends them back through a logging/capture tool.
- Codex-style MCP smoke passed for context and capture tools; Claude Desktop-specific smoke is deferred and not part of the immediate build plan.
- OCR direction is fully local. Users should not manually install OCR dependencies for shipped builds.
- OCR shipping caveat: Ghostscript is treated as an AGPL-compatible public-release dependency unless replaced or commercially licensed later; package smoke alone is not enough.
- Tesseract is Apache 2.0; qpdf is acceptable for bundling review; Ghostscript needs AGPL/commercial decision.
- Runtime crash during generation should mark active generation retriable or failed-runtime without touching vault lock state.
- Background jobs need explicit restart policies: `requeue`, `reconcile_then_retry`, or `manual_review`.
- Contributor requirements must stay updated whenever dependencies/import requirements change.
- Keep this document ruthlessly pruned. If a note is no longer actionable or current, remove it.

## Update Protocol

At the end of every meaningful task:

1. Update `Last updated`.
2. Update relevant progress bars.
3. Update `Current Critical Path` if priorities changed.
4. Add only high-signal completed work to `Recent Completed Work`.
5. Add/remove blockers and open work instead of appending duplicates.
6. Preserve non-negotiable running notes.
7. Prune at least one stale or duplicated note when the file grows.
8. Keep detailed test logs, long histories, and one-off reports in dated docs, not here.
