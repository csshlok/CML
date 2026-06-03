# Project Context And Progress

Last updated: 2026-06-03

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

Public V1 target: end of July 2026, only if public-quality gates pass. If blockers remain, ship as private alpha/demo, not a public product for real user data.

## Current Product Decisions

- Product form: local downloadable desktop app, not a web app.
- Desktop shell: Electron in `apps/desktop`.
- Backend: FastAPI in `backend`.
- V1 vault scope: explicit vault mode only; no full-device silent scanning.
- V1 storage: local vault folder with `CML_DATA_DIR=<vault>/.vault` and `CML_DATABASE_PATH=<vault>/.vault/cml.sqlite3`.
- V1 integrations: local synced folders first, including Google Drive Desktop, Dropbox, OneDrive, iCloud Drive, Obsidian folders, and normal folders.
- Later integrations: OAuth/API connectors after local ingestion is stable.
- UI direction: memory-board landing, visual map, chat workspace, Mindly-like organization, Obsidian-like graph/map.
- UI responsive scope: no dedicated mobile screen for public V1; dark version and minimized/narrow desktop window version are required.
- UI reference folder: preserve `UI-ref/`; do not delete or refactor it.
- Cluster experts: compulsory product pillar.
- Public V1 expert claim: only say a cluster expert is trained after verified LoRA adapter graduation passes for that cluster.
- Local-first privacy: user data stays local unless the user explicitly exports or connects a tool.
- External access: Context Bridge through MCP, local HTTP API, CLI, and copy/export.

## Model And Runtime Decisions

Do not bundle LLM weights in the first installer. First-run setup should let users download CML-managed local models or connect existing local runtimes.

| Role | Default / Option | ID | Repo | Approx size | Target RAM |
| --- | --- | --- | --- | --- | --- |
| Default synthesis | Qwen3 4B Q4_K_M | `qwen3-4b-q4_k_m` | `Qwen/Qwen3-4B-GGUF` | ~2.5 GB | 8+ GB |
| Low-spec fallback | Phi-4 Mini Instruct Q4_K_M | `phi-4-mini-instruct-q4_k_m` | `unsloth/Phi-4-mini-instruct-GGUF` | ~2.5 GB | 8+ GB |
| Quality option | Qwen3 8B Q4_K_M | `qwen3-8b-q4_k_m` | `Qwen/Qwen3-8B-GGUF` | ~4.8 GB | 16+ GB |
| Optional later | Gemma 3 4B IT Q4_K_M | `gemma-3-4b-it-q4_k_m` | `Aldaris/gemma-3-4b-it-Q4_K_M-GGUF` | ~2.5 GB | 8+ GB |
| Optional later | Gemma 3 12B IT Q4_K_M | `gemma-3-12b-it-q4_k_m` | `nocturne23/gemma-3-12b-it-Q4_K_M-GGUF` | ~6.9 GB | 24+ GB |

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
| Product definition | In progress | `[#########-] 97%` | Final installer/update policy and release cut line |
| UI prototype cleanup | In progress | `[##########] 99%` | Dark QA, minimized/narrow desktop QA, packaged-flow polish |
| Desktop app foundation | In progress | `[#########-] 95%` | Runtime process management and broader packaged startup repair QA |
| Local backend foundation | In progress | `[##########] 99%` | Broader recovery drills and service-layer cleanup |
| Vault ingestion | In progress | `[##########] 99%` | Packaged dynamic-link/browser-runtime QA |
| Embeddings and clustering | In progress | `[##########] 96%` | Broader threshold tuning on real user vaults and merge artifact policy |
| Chat/context routing | In progress | `[#########-] 94%` | Complete-scope map/reduce, token budgets, retention policy, runtime failure UX |
| Compulsory cluster experts | In progress | `[#####-----] 50%` | Real adapter smoke, runtime adapter loading, metrics, rollback, failure states |
| Context Bridge | In progress | `[#########-] 92%` | Real Claude Desktop smoke and capture UX polish |
| Packaging/install | In progress | `[########--] 78%` | Update/migration policy, Ghostscript licensing decision, packaged browser-runtime QA |
| QA/hardening | In progress | `[##########] 95%` | Larger benchmarks on real user vaults, real Claude Desktop smoke, recovery drills |

## Current Critical Path

- Finish remaining packaged app smoke: dynamic-link/browser runtime, full-vault vault selection path, diagnostics export, update/migration policy.
- Keep public V1 public-only criteria. If gates fail, label the build private alpha/demo.
- Verify real adapter training and runtime loading before any broad "trained expert" claim.
- Continue retrieval threshold tuning beyond the new real user-shaped benchmark using larger user-owned vaults.
- Smoke Context Bridge against Claude Desktop before advertising MCP readiness.
- Treat the Codex-style MCP smoke as a first client-path pass, not a substitute for Claude Desktop verification.
- Keep project context concise enough for session continuity.

## Phase Snapshot

Product definition:

- Done: PRDs, local-first product boundary, public V1 quality bar, public-only release stance.
- Remaining: final release cut line, supported OS decision, installer/update policy.

UI prototype cleanup:

- Done: main desktop surfaces, generated-reference alignment, backend-first data loading for core areas.
- Remaining: no new UI work now unless requested; later dark version, minimized/narrow desktop, packaged visual QA.

Desktop app foundation:

- Done: Electron workspace, backend launch/token seams, vault lock override flow, file picker/open/reveal IPC, packaged pre-vault launch smoke, packaged main-process runtime logging.
- Remaining: broader packaged startup repair QA, process lifecycle hardening, full-vault launch smoke.

Local backend foundation:

- Done: FastAPI core, SQLite schema, auth/token hardening, diagnostics, startup repair summary, vector maintenance endpoints, storage accounting, interrupted-migration repair signal.
- Remaining: service-layer cleanup and more packaged/recovery drills.

Vault ingestion:

- Done: files, folders, links, text, Markdown/Obsidian metadata, PDFs, images, OCR runtime health, OCR jobs, per-page OCR job progress, page/chunk storage, dynamic-link fallback.
- Remaining: packaged browser-runtime smoke for dynamic links.

Embeddings and clustering:

- Done: default real embedding direction, hash dev fallback boundary, vector repair/compaction/policy endpoints, startup reconciliation, BM25 plus embedding scoring ledger, source-class weighting, threshold benchmark harness, retrieval eval fixtures, real T-drive cancellation smoke, 100-source benchmark script/report export, active-index transition smoke, real second-embedding cache smoke, user-shaped vault benchmark export.
- Remaining: broader threshold tuning on user-owned vaults, merge artifact policy.

Chat/context routing:

- Done: LLM-first routing, retrieval intent, degraded runtime states, citation snapshots, attachment ingestion, coverage ledger, expanded-analysis foundation, chat message pagination, retrieval snapshot compaction.
- Remaining: real complete-scope map/reduce, partial-failure classification, token budgets, retention policy, evidence cache pruning.

Compulsory cluster experts:

- Done: verified-LoRA contract scaffold, dataset export, artifact schema, metrics, activation, rollback, delete guardrails, tests.
- Remaining: do not touch for now unless requested; real LLaMA Factory smoke, runtime adapter loading, hardware matrix, quality benchmark.

Context Bridge:

- Done: bridge tokens, permissions, token rotation, stale allowlist pruning, no-active-vault errors, notification behavior, constant-time token compare, explicit external-turn/artifact capture tools with vault/cluster permission checks, Codex-style MCP JSON-RPC smoke, malformed-client hardening.
- Remaining: full extension package, real Claude Desktop smoke, capture UX polish.

Packaging/install:

- Done: Windows package scripts, contributor requirements, OCR runtime staging script, local staged OCR runtime, rebuilt NSIS installer, silent install/uninstall smoke, packaged OCR verification, packaged model/embedding setup smoke.
- Remaining: update/migration policy, Ghostscript licensing decision, packaged dynamic browser-runtime QA.

QA/hardening:

- Done: broad backend regression coverage, OCR benchmarks, audits, diagnostic redaction/log-rotation policy, backend benchmark scripts, disposable-vault delete cleanup tests, failed embedding-write retry test, dynamic-link browser-runtime smoke with Playwright on `T:`, Codex-style MCP smoke, real second-embedding model/cache smoke, repeatable packaging/security smoke scripts, npm and Python vulnerability audits.
- Remaining: larger user-vault benchmarks, real Claude Desktop smoke, recovery/failure drills.

## Public V1 Blockers

These are release gates, not polish.

- Vault data path correctness: backend data and database must live under the selected vault folder in full-vault mode.
- Pre-vault/full-vault lifecycle: restricted pre-vault backend must block vault/source/chat/search/bridge data routes until a vault is selected.
- Startup repair: packaged pre-vault launch reaches ready; full-vault repair-path drills and visible repair UI still need broader packaged QA.
- Migration durability: schema versioning exists, but interruption/recovery tests and real migration scripts must mature as schema changes continue.
- Disk preflight: installer/model/OCR/indexing/ingestion flows need required/available space checks.
- Local API auth: Electron-managed private APIs need token gate and renderer-origin validation; Bridge tokens stay separate.
- Embedding setup gate: production cannot silently use hash embeddings; semantic features must block/degrade explicitly when embeddings are unavailable.
- Scheduler synthesis gate: background jobs that should not run during generation must respect active/retriable generation states.
- Chat recovery: interrupted generations need durable timeline placeholders, retry actions, and no fake assistant messages.
- Complete analysis: current broad rerun is `expanded_analysis`; reserve `complete_analysis` for future evidence-packet map/reduce and return `501` if requested before implementation.
- Deletion graph: deleted sensitive content must disappear from retrieval/search immediately before async cleanup.
- Diagnostics: log rotation policy exists; packaged-path diagnostics export smoke remains.
- MCP Bridge: Codex-style JSON-RPC smoke passed; real Claude Desktop smoke and clear app error codes are still required before advertising MCP readiness.
- LoRA: public V1 requires verified real adapter training, adapter artifact, runtime load, rollback, supported hardware, failure codes, and quality win over retrieval baseline.
- OCR/package: packaged OCR runtime and installer smoke pass, but Ghostscript licensing decision remains before shipping to users.

## Next Backend Build Steps

Scope constraints for this list: no LoRA implementation, no UI work, no package rebuild unless explicitly requested.

1. Run real Claude Desktop MCP smoke for context, external-turn logging, artifact capture, malformed calls, and notification silence.
2. Expand retrieval threshold tuning from the 100-source user-shaped benchmark into a larger user-owned vault fixture.
3. Add merge artifact policy for clustering: provenance, reversible merge metadata, and split/rollback behavior.
4. Harden query/evidence cache lifecycle with age limits, max bytes, and stale citation cleanup.
5. Add stable cursor semantics for chat pagination across equal timestamps and deleted-message gaps.
6. Extend source-class weighting calibration to multi-turn chats, screenshots/OCR, and external captures.
7. Move more route-level source/chat/search database logic into service modules with transaction boundaries.
8. Add extension pairing expiry/replay hardening and audit filtering by client/source/vault.
9. Add startup repair recovery cases for failed migrations once the next real migration exists.
10. Add repeatable contributor dependency/security audit command for Python backend dependencies.

## Current Open Work

- Decide first supported OS for downloadable public V1.
- Finish first-run setup around vault path, model setup, embedding setup, OCR readiness, and startup repair states.
- Add one-click local model/embedding dependency install or connect-existing-runtime flows.
- Continue backend service-layer extraction around raw route/database operations.
- Finish packaged ingestion verification for scanned PDFs, image OCR, and dynamic links.
- Add complete-scope answering in stages: coverage ledger, BM25/embedding scoring, threshold tuning, map packets, reduce/synthesis, cache pruning.
- Add query/evidence cache retention limits beyond the new source-ID invalidation path.
- Add chat retention policy and deleted/stale citation actions beyond the new pagination and snapshot compaction endpoints.
- Finish local synced-folder import history and watched refresh polish where gaps remain.
- Build actual browser extension package and safer pairing flow.
- Add real Claude Desktop smoke before Bridge claims production readiness.
- Smoke MCP external-turn capture tools against Claude Desktop after the Codex-style MCP smoke.
- Keep Python dependency CVE auditing in repeatable contributor QA.
- Keep LoRA untouched unless explicitly requested; public V1 still requires verified LoRA later.

## Recent Completed Work

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

- Public V1 only: if there is a V1, it must be public-quality. Otherwise call it private alpha/demo.
- Public V1 selling point is verified LoRA, but do not touch LoRA implementation right now unless explicitly requested.
- User-facing "trained expert" language is allowed only after real adapter graduation.
- No package rebuild work unless explicitly requested.
- No UI implementation unless explicitly requested; dark version and minimized/narrow desktop version are noted future requirements.
- Do not delete or alter `UI-ref/`.
- Playwright browser runtime for local dynamic-link smoke is installed on `T:\CML-playwright-browsers`; contributor backend requirements now include `playwright==1.60.0`.
- Packaging smoke scripts clear inherited `ELECTRON_RUN_AS_NODE`; otherwise packaged Electron launches in Node mode and will not execute app startup.
- Hash embeddings are development-only and must not be a silent production fallback.
- SQLite is authoritative; vector indexes are derived and rebuildable.
- Deleted sources must be excluded at SQLite/filter layer immediately, before async vector cleanup.
- Startup order: vault ownership, SQLite integrity/schema/migrations, job recovery, vector/index reconciliation, runtime detection, then API/UI traffic.
- `complete_analysis` is reserved for future map/reduce. Current broad path is `expanded_analysis`.
- MCP Bridge must not respond to JSON-RPC notifications.
- MCP Bridge must return explicit app errors like `1001 no_active_vault`; never silently choose the first vault.
- MCP cannot automatically see outside model responses; external transcripts are capturable only when the MCP client explicitly sends them back through a logging/capture tool.
- Codex-style MCP smoke passed for context and capture tools; Claude Desktop smoke is still required before claiming MCP production readiness.
- OCR direction is fully local. Users should not manually install OCR dependencies for shipped builds.
- OCR shipping caveat: Ghostscript licensing must be decided before proprietary distribution; package smoke alone is not enough.
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
