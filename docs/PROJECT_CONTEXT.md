# Project Context And Progress

Last updated: 2026-06-12

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
- Desktop brand asset: use only `apps/desktop/public/brand/vault-logo.png` and `apps/desktop/public/brand/vault-icon.png` for Vault branding; do not reintroduce favicon-derived or ad hoc logo variants in the UI.
- Cluster experts: compulsory product pillar.
- Public V1 expert claim: only say a cluster expert is trained after verified LoRA adapter graduation passes for that cluster.
- Local-first privacy: user data stays local unless the user explicitly exports or connects a tool.
- External access: Context Bridge through MCP, local HTTP API, CLI, and copy/export.
- V1 security boundary: full security work is in public V1, not deferred. If encryption, unlock-state enforcement, parser/browser isolation, Bridge approval, renderer hardening, or LoRA integrity are not release-ready, release slips.
- Vault recovery model: offline recovery key, generated locally, never stored server-side, with explicit user acknowledgment during setup.
- Vault unlock modes: convenience mode is the default; strict locked mode is opt-in and must stay visible in Settings.
- Convenience mode may use an optional 6-digit local PIN for fast re-entry, but the PIN is not the primary vault security boundary and must not replace the full passphrase for sensitive operations.
- Strict locked mode requires passphrase re-entry after backend restart or explicit lock and pauses vault-bound background processing while locked.

## Model And Runtime Decisions

Do not bundle LLM weights in the first installer. First-run setup must require one CML-managed approved model download or import before normal expert-capable use. Model choice must be recommended from the user's actual system conditions, not one default that assumes a high-end machine.

| Role | Default / Option | ID | Repo | Approx size | Target RAM |
| --- | --- | --- | --- | --- | --- |
| Default synthesis | Qwen3 4B Q4_K_M | `qwen3-4b-q4_k_m` | `Qwen/Qwen3-4B-GGUF` | ~2.5 GB | 8+ GB |
| Low-spec fallback | Phi-4 Mini Instruct Q4_K_M | `phi-4-mini-instruct-q4_k_m` | `unsloth/Phi-4-mini-instruct-GGUF` | ~2.5 GB | 8+ GB |
| Quality option | Qwen3 8B Q4_K_M | `qwen3-8b-q4_k_m` | `Qwen/Qwen3-8B-GGUF` | ~4.8 GB | 16+ GB |
| Optional later | Gemma 3 4B IT Q4_K_M | `gemma-3-4b-it-q4_k_m` | `Aldaris/gemma-3-4b-it-Q4_K_M-GGUF` | ~2.5 GB | 8+ GB |
| Optional later | Gemma 3 12B IT Q4_K_M | `gemma-3-12b-it-q4_k_m` | `nocturne23/gemma-3-12b-it-Q4_K_M-GGUF` | ~6.9 GB | 24+ GB |

Approved-model policy:

- Public V1 now uses a dual-model runtime structure with strict acceptance rules.
- Chat/runtime models and expert-base models are different roles and must not be treated as interchangeable, even when they come from the same family.
- Current default choices remain the current Qwen/Phi/Gemma defaults for recommendation purposes.
- Custom models still have only two outcomes: `accepted` or `rejected`.
- Acceptance must become role-aware: a model or model pair is accepted only if CML proves it is compatible with the intended chat role, expert role, or approved pairing on the current machine.
- Connected OpenAI-compatible runtimes, GGUF-only aliases, Ollama names, and llama.cpp endpoints are not sufficient by themselves for LoRA acceptance.
- Expert training/runtime must use an app-managed compatible local checkpoint under an app-managed path.
- Setup must require an accepted configuration before expert-capable onboarding completes. Retrieval-only degraded mode may still exist explicitly, but it does not satisfy the intended V1 setup path.
- Citation authority must remain Vault retrieval, not model memory. Expert models may assist with cluster-specific reasoning, but citations must be produced from retrieved source records.
- Public docs and UI must stop implying that one approved family automatically means one lightweight runtime path. Current code still implies separate chat and expert runtime costs.

Dual-model runtime decision:

- Chat role: user-facing synthesis model for normal conversation and final answer writing.
- Expert role: cluster-specialized LoRA-capable model/runtime used only when expert routing is justified.
- Retrieval layer: source of truth for evidence, snippets, and citations for both roles.
- Routing order: user query -> intent/routing -> retrieval -> optional expert assist -> final chat answer with citations from retrieval.
- Do not design the system so the expert model becomes the authority that later receives citations as decoration.
- Approved model support must move toward an approved compatibility matrix of chat role, expert role, and approved pairings rather than a single loose runtime identity.
- Current code path still uses llama.cpp or another OpenAI-compatible local runtime for chat and a separate Transformers/PEFT runtime for expert work. Treat this as the current architecture unless explicitly refactored.
- Because the current expert runtime loads a real Transformers checkpoint, expert mode should be treated as a higher-spec feature. Provisional public stance: do not promise expert mode on 8 GB machines; require real profiling before publishing a lower bound.

Required recommendation system:

- Detect RAM, CPU threads, OS, architecture, AVX2, GPU/CUDA availability where possible, free disk, and currently configured local runtime.
- Recommend a low-spec, standard, or quality model tier with plain-language reasoning.
- Never recommend a model that is likely to make the app unusable on the current machine.
- Current default choices remain the default recommended families unless hardware or licensing constraints force a smaller approved option.
- If the user imports their own model, run a compatibility report before registration and reject it with explicit reasons when it fails the approved contract.
- Keep retrieval/context-only mode available as an explicit degraded state, but not as the desired public V1 experience.
- Treat chat-runtime sizing and expert-runtime sizing separately in user guidance and setup validation.
- Recommend only approved compatible chat/expert pairings once the pairing matrix exists; do not allow arbitrary pair combinations.
- On rejected custom model imports, provide an explicit replacement recommendation for the current hardware tier.

Runtime boundary:

- Use an OpenAI-compatible local runtime endpoint where possible.
- Support llama.cpp via `llama-server`.
- Support Ollama only when OpenAI-compatible behavior is confirmed.
- If no synthesis runtime is configured, use explicit degraded/context-only responses; do not silently pretend local chat works.
- Cluster experts are not allowed to rely on arbitrary connected runtime identities; expert runtime must resolve an accepted local checkpoint directly.
- Hash embeddings are development-only. Public/product setup must require a real local embedding backend or explicit degraded mode.

## Phase Progress

| Phase | Status | Progress | Remaining gate |
| --- | --- | --- | --- |
| Product definition | In progress | `[##########] 99%` | Windows-only public release decision record |
| UI prototype cleanup | In progress | `[##########] 99%` | Dark QA, minimized/narrow desktop QA, packaged-flow polish |
| Desktop app foundation | In progress | `[##########] 98%` | Clean VM launch validation and broader startup repair QA |
| Local backend foundation | Complete for current scope | `[##########] 100%` | Future service-layer cleanup only |
| Vault ingestion | Complete for current scope | `[##########] 100%` | Clean VM confirmation only |
| Embeddings and clustering | Complete for current scope | `[##########] 100%` | Larger real-vault evidence now lives under QA/hardening |
| Chat/context routing | In progress | `[##########] 97%` | Complete-scope map/reduce, token budgets, runtime failure UX |
| Compulsory cluster experts | In progress | `[#########-] 90%` | Real machine validation still required for LLaMA Factory smoke, live adapter prompt run, and live quality benchmark |
| Context Bridge | In progress | `[#########-] 95%` | Capture UX polish, clearer privacy copy, and later external-client smoke |
| Packaging/install | In progress | `[#########-] 96%` | Clean VM validation plus installed-app startup/install diagnostics remain required; do not rely on the older missing-resources state |
| QA/hardening | In progress | `[##########] 99%` | Clean VM package validation, larger user-owned vault benchmarks, and hardware-aware model recommendation QA |
| Security | Complete except LoRA Phase 11 | `[##########] 100%` | Phases 0-10 and 12-14 complete; only LoRA-specific Phase 11 is intentionally deferred until LoRA is ready |

## Current Critical Path

- Keep Windows packaging work focused on the current failures, not the older missing-resource state: the package has already moved past relocatable-runtime and missing-resources bugs, so the remaining gate is clean VM validation, installed-app parity smokes, and any installer/runtime failures reproduced there.
- Execute clean Windows VM validation against a complete package: no dev Python, no Node, no preinstalled OCR, cold first-run.
- Current Hyper-V VM attempt is not yet a trustworthy clean-machine gate: the Windows 11 Home guest `VM-1` was reachable, but the packaged installer `CML-0.1.0-Setup.exe` crashed inside the guest with `System.dll` / `0xc0000005`, and the guest also showed Windows servicing/component-store failures plus unstable PowerShell Direct sessions. Treat this as an environment-quality blocker until rerun on a healthier clean VM image.
- Installer UX gap from older manual review is now closed in config: the generated NSIS config enables install-directory selection and desktop/start-menu shortcut creation. Remaining installer work is first-run reliability and clean-VM validation, not those older UX toggles.
- Keep the non-LoRA security patch closed while LoRA-specific Phase 11 remains intentionally deferred until the LoRA runtime/training path is ready to harden.
- Keep Windows-only public V1 criteria. If verified LoRA or other public gates fail, delay release; do not ship a private demo fallback.
- Verify real adapter training and runtime loading before any broad "trained expert" claim.
- Compulsory expert work now has stricter dataset/diversity/quality gates, evaluation harness, passing CI scaffold smoke, runtime dependency visibility, and Expert tab visibility, but still needs a real trainer command/model path before public claims.
- Validate the new accepted/rejected model contract on a clean Windows machine with the bundled expert runtime and one imported approved checkpoint.
- Update threat/privacy docs so Bridge is described honestly as token/scoped but not meaningfully throttled against repeated corpus walking by a trusted client.
- Dynamic link browser fallback now runs through an isolated worker boundary and browser-derived content is gated as low-trust before synthesis; keep validating packaged/clean-VM behavior before public claims.
- Keep the written threat model current and treat local API/Bridge auth regressions as release blockers.
- Continue retrieval threshold tuning beyond the synthetic 1k benchmark using larger user-owned or natural-corpus vaults.
- Turbovec Phase A and B are now implemented: SQLite stays authoritative, semantic search is routed through a vector-backend abstraction, `turbovec` sidecars are buildable/repairable per `vault_id + derived_state_epoch`, and Phase C remains gated on the benchmark thresholds in `docs/TURBOVEC_INTEGRATION_PLAN.md` before any default-on rollout for healthy vaults with `>= 10,000` chunks.
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

- Done: FastAPI core, SQLite schema, fail-closed local API auth, authenticated backend identity endpoint, FastAPI lifespan migration, atomic job claiming, diagnostics, startup repair summary, vector maintenance endpoints, storage accounting, interrupted-migration repair signal, lightweight first-run readiness summaries, and cached local model discovery for repeated readiness/discovery checks.
- Remaining: future service-layer cleanup and continued recovery drills as schema changes.

Vault ingestion:

- Done: files, folders, links, text, Markdown/Obsidian metadata, PDFs, images, OCR runtime health, OCR jobs, per-page OCR job progress, page/chunk storage, dynamic-link fallback, packaged generated image/PDF OCR smoke, packaged dynamic-link/browser-runtime smoke.
- Remaining: clean VM confirmation only.

Embeddings and clustering:

- Done: default real embedding direction, hash dev fallback boundary, vector repair/compaction/policy endpoints, startup reconciliation, BM25 plus embedding scoring ledger, source-class weighting, threshold benchmark harness, retrieval eval fixtures, real T-drive cancellation smoke, 100-source benchmark script/report export, active-index transition smoke, real second-embedding cache smoke, user-shaped vault benchmark export, 1k benchmark script with timing targets, watched-folder back-pressure limits, cluster merge artifacts and rollback, active-embedding filtering across retrieval/search paths so mixed embedding spaces are not ranked together, exact semantic search now reads the active vector-index policy selector, and completed turbovec Phase A/B wiring: benchmark harness, vector-backend abstraction, live semantic-search integration, sidecar build/status/repair endpoints, incremental sidecar updates on reindex/delete, manifest validation/path hardening, and startup-repair coverage.
- Remaining: broader threshold tuning on user-owned vaults, current exact-scan breaking-point measurement on larger natural PDF corpora, and the locked Phase C acceptance benchmark pass for default-on `turbovec` on healthy `>= 10,000`-chunk vaults.

Chat/context routing:

- Done: LLM-first routing, retrieval intent, degraded runtime states, citation snapshots, attachment ingestion, coverage ledger, expanded-analysis foundation, chat message pagination, retrieval snapshot compaction, query/evidence cache pruning, evidence retention policy/enforcement API, explicit product framing that retrieval remains citation authority while expert models assist with reasoning, automatic synthesis token-budget accounting/trimming, retrieval-snapshot token-budget persistence, and structured partial-failure modes for embedding-unavailable, low-trust extract-only, and runtime-fallback chat paths.
- Remaining: real complete-scope map/reduce, richer runtime failure UX in the desktop flow, and deeper expert-assisted routing beyond the current contract/state split.

Compulsory cluster experts:

- Done: verified-LoRA contract scaffold, dataset export with source/token/diversity counts, duplicate-ratio gate, artifact schema, metrics, activation, rollback, delete guardrails, shell-free trainer process boundary, Windows-path trainer tests, stricter graduation contract, adapter config/weight validation, runtime-load plan metadata, deterministic expert evaluation harness, retrieval-vs-adapter delta gate, stale-adapter detection, Expert tab status UI, and a passing CI-only LoRA expert scaffold smoke that drains queued source-indexing and training jobs.
- Remaining: execute the new Transformers/PEFT runtime smoke on a real machine with an installed accepted local base model, record a real LLaMA Factory trainer run against that model, expand hardware matrix/time estimates, replace deterministic adapter scoring with a live adapter-backed quality benchmark, and convert the model story from one-family wording to an explicit approved chat/expert pairing matrix.

Context Bridge:

- Done: bridge tokens, permissions, token rotation, stale allowlist pruning, no-active-vault errors, notification behavior, constant-time token compare, explicit external-turn/artifact capture tools with vault/cluster permission checks, Codex-style MCP JSON-RPC smoke, malformed-client hardening, and explicit threat-model wording that Bridge is trusted-client scoped access rather than a meaningful anti-exfiltration throttle.
- Remaining: full extension package, capture UX polish, later external-client smoke when reprioritized.

Packaging/install:

- Done: Windows package scripts, contributor requirements, OCR runtime staging script, local staged OCR runtime, NSIS installer path, silent install/uninstall smoke scripts, packaged OCR/model/embedding/full-vault/dynamic-link/migration/app-launch smoke scripts, clean-machine validation script, and AGPL-compatible Ghostscript release policy.
- Remaining: clean VM validation is still required, and packaging/debug docs need to stay aligned with the newer runtime state so operators do not chase the older missing-resource failure after the package has already moved on to later installer/runtime issues.

QA/hardening:

- Done: broad backend regression coverage, atomic job concurrency tests, local API auth/identity tests, OCR benchmarks, audits, diagnostic redaction/log-rotation policy, backend benchmark scripts with durable JSON/Markdown report output, disposable-vault delete cleanup tests, failed embedding-write retry test, dynamic-link browser-runtime smoke with Playwright, real second-embedding model/cache smoke, repeatable packaging/security smoke scripts, npm and Python vulnerability audits, threat model, synthetic 1k benchmark harness/pass, startup stale-phase validation tests, recovery drills endpoint, first-run readiness gate tests, readiness light-probe regression coverage, and model-discovery cache regression coverage.
- Remaining: larger user-owned/natural-corpus vault benchmarks, clean VM package validation, hardware-aware model recommendation QA.

Security:

- Done: local-only security architecture, unlock state machine, derived-state/migration rules, build-plan specs, Phase 0 baseline audit, Phase 1 crypto/metadata foundation, Phase 2 unlock/API gating, Phase 3 encrypted storage/blob boundary, Phase 4 derived-state tuple publication, Phase 5 migration planner/staging GC, Phase 6 quarantine/parser worker isolation, Phase 7 Playwright/link isolation, Phase 8 retrieval trust gate/prompt safety, Phase 9 renderer hardening, Phase 10 Bridge approval/identity, Phase 12 reconciliation logging/locked-mode supportability, Phase 13 packaging/runtime hardening, and Phase 14 end-to-end security QA. Phase 8 adds trust metadata to retrieval candidates, trust-aware ranking, final-evidence classification before synthesis, sensitive low-trust refusal, all-low-trust degraded extractive output, low-trust synthesis caps, and quoted evidence prompts.
- Remaining: only Phase 11 LoRA-specific hardening is intentionally deferred until LoRA itself is finished enough to patch against.

## Public V1 Blockers

These are release gates, not polish.

- Vault data path correctness: backend data and database must live under the selected vault folder in full-vault mode.
- Pre-vault/full-vault lifecycle: restricted pre-vault backend must block vault/source/chat/search/bridge data routes until a vault is selected.
- Startup repair: packaged pre-vault launch reaches ready and packaged migration drill passes; visible repair UI still needs broader clean-VM/package QA.
- Migration durability: schema versioning exists, but interruption/recovery tests and real migration scripts must mature as schema changes continue.
- Disk preflight: installer/model/OCR/indexing/ingestion flows need required/available space checks.
- Local API auth: Electron-managed private APIs now fail closed without the local API token; renderer-origin validation and Bridge-token separation remain release gates.
- Auth threat model: written in `docs/THREAT_MODEL.md`; keep it updated and enforce it through release-gate tests before public V1.
- Vault encryption and unlock boundary: public V1 requires passphrase-based encrypted vault storage, offline recovery key flow, convenience-vs-strict lock modes, unlock-time verification, and no silent backend restart bypass.
- Embedding setup gate: production cannot silently use hash embeddings; semantic features must block/degrade explicitly when embeddings are unavailable.
- Embedding transition correctness: retrieval/search must not silently mix vectors from different embedding models. The core filter hotfix is now in place; keep regression coverage and any remaining retrieval paths aligned with the same selector.
- Derived-state correctness: retrieval must use a snapshotted active tuple for normalization, embedding, and extraction versions; mixed or partially published tuples must never serve one query.
- Model integrity: managed model downloads record SHA-256 and verify real pinned expected hashes from `docs/model-integrity-manifest.json`.
- Scheduler synthesis gate: background jobs that should not run during generation must respect active/retriable generation states.
- Chat recovery: interrupted generations need durable timeline placeholders, retry actions, and no fake assistant messages.
- Complete analysis: current broad rerun is `expanded_analysis`; reserve `complete_analysis` for future evidence-packet map/reduce and return `501` if requested before implementation.
- Deletion graph: deleted sensitive content must disappear from retrieval/search immediately before async cleanup.
- Diagnostics: log rotation policy exists; keep packaged full-vault diagnostics export revalidated whenever packaging/runtime behavior changes.
- MCP Bridge: Codex-style JSON-RPC smoke passed; keep external-client readiness claims conservative while Claude Desktop-specific smoke is deferred.
- Bridge privacy boundary: current Bridge auth/scope model is not a meaningful anti-exfiltration throttle once a trusted client has a valid token for an allowed vault/cluster set. Threat-model wording and UI privacy language must say this plainly.
- Bridge approval boundary: Phase 10 now enforces locked-state failure, public approval request creation with short-lived polling codes, explicit claimed-vs-observed identity UI, shared-token disablement for secured runtime Bridge calls, encrypted approval/client metadata, revocation, audit events, and bounded Bridge usage history.
- Renderer safety: Phase 9 now enforces escaped text rendering for model/document output through a static renderer sink audit, hostile output fixture, packaged CSP headers, and Electron behavior coverage.
- LoRA: public V1 requires verified real adapter training, adapter artifact validation, runtime load against a real local model, rollback, supported hardware, failure codes, and quality win over retrieval baseline.
- LoRA graduation framing: small or insufficient clusters should remain retrieval-backed with explicit status instead of pretending every cluster can graduate.
- LoRA threshold honesty: current token/source defaults are scaffolding values, not benchmark-backed public gates. Raise or replace them before public claims.
- LoRA trust boundary: public V1 requires dataset manifest review, low-trust source exclusion by default, runtime adapter/base-model hash verification, and no grandfathering of pre-integrity artifacts as trusted.
- Expert runtime sizing: current expert runtime is a separate Transformers/PEFT load path, not a lightweight extension of the chat runtime. Public expert-mode hardware requirements must be measured and stated honestly.
- Model recommendation: public V1 must recommend safe synthesis/embedding/expert setup by detected system tier, enforce one approved model family contract, and reject incompatible custom imports explicitly.
- OCR/package: package smoke scripts and previous package/runtime passes are recorded, but clean VM validation and current-state packaging documentation are still release gates. Ghostscript path remains AGPL-compatible public release.
- Dynamic-link browser fallback: Playwright/Chromium fallback now uses an isolated worker with request budgets, private/local/file blocking, download disabling, parent-side output validation, browser-derived low-trust provenance, and pre-synthesis retrieval trust gates. Remaining public-V1 work is packaged/clean-VM verification.
- Cloud-synced vault path safety: selecting a OneDrive/iCloud/other synced vault path is currently not robustly warned/blocked. Treat this as a storage-integrity gap for public V1.
- Diagnostics redaction: current bundle redaction is regex-based and does not yet amount to a rigorous "no secrets can leak" guarantee.

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
- Continue hardening the Phase 3 storage boundary where later phases add new sensitive artifacts: retrieval snapshots, analysis packets, adapter artifacts, staged derived-state artifacts, and quarantine payloads must use encrypted content/blob storage instead of plaintext fields.
- Finish first-run setup UI around the new readiness gate: vault path, model setup, embedding setup, OCR readiness, startup repair states.
- Make onboarding honest about local model/embedding download size, time, hardware requirements, and external Bridge privacy tradeoffs.
- UI follow-up: separate the purpose and presentation of `Home` versus `Mind`, and verify packaged startup routes first-run users into onboarding instead of dropping them into the main app shell.
- Continue validating Phase 5 migration safety on large real vaults, but core disk-preflight, staged-publication start, bounded GC, and disk-full old-tuple preservation are implemented.
- Done: Phase 12 reconciliation logging and locked-mode supportability. Integration imports now persist encrypted post-unlock reconciliation summaries/details, bounded detail pagination, per-item retry, retention/compaction, and no external locked-mode pending-work signal.
- Add real checkpoint-family download/import UX for the approved model contract, beyond the current runtime/GGUF default downloads.
- Define and implement the approved chat-role / expert-role pairing matrix, including hardware tiers and explicit rejected-pair reasons.
- Add model provenance display in setup/settings using `/api/v1/models/integrity-manifest`.
- Continue backend service-layer extraction around raw route/database operations.
- Add complete-scope answering in stages: coverage ledger, BM25/embedding scoring, threshold tuning, map packets, reduce/synthesis, cache pruning.
- Finish local synced-folder import history and watched refresh polish where gaps remain.
- Build actual browser extension package and safer pairing flow.
- Execute the clean-machine package script and smoke sequence on a fresh Windows VM before public release claims.
- Keep Python dependency CVE auditing in repeatable contributor QA.
- Continue LoRA readiness gates now that expert work is active: real trainer smoke, live runtime load, live adapter benchmark, hardware matrix, rollback edge cases, Expert tab controls, and benchmark-backed training eligibility thresholds.
- Update docs/UI wording so retrieval remains the citation authority and expert models are described as reasoning assistants, not as the source of proof.
- Add robust vault-location warnings or blocks for cloud-synced paths used as the main vault location.

## Recent Completed Work

- Fixed a real source-identity bug cluster in the backend. Generic source creation no longer collapses different manual notes or different file paths together only because their text or checksum matches, while same-path and same-URL re-imports now update the existing source instead of silently creating duplicates. This brings manual source behavior back in line with real user expectations for repeated imports and duplicate-content files at scale. Verification: `.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_source_pages.py -k "manual_path_ingestion or duplicate_manual_notes or chat_attachment"` passed with `4` tests; `.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_additional_qa_cases.py -k "modified_file_after_first_ingest_updates_same_source"` passed with `1` test; `python -m compileall backend/app` passed.
- Fixed a real chat attachment ownership and secured-cleanup bug cluster in the backend. Chat attachment ingestion no longer reuses and silently re-clusters an existing normal vault source just because the checksum matches, and chat-session deletion now performs full chat-owned source cleanup for secured vaults instead of doing blind raw deletes that could leave encrypted-content rows behind. Session deletion also now preserves normal sources that were merely attached in chat while still marking downstream citations as `source_deleted` when a true chat-owned attachment source is removed. Removed a stale duplicate transcript-source helper from `backend/app/api/routes/chat.py` so transcript indexing logic remains single-sourced in `backend/app/core/chat_memory.py`. Verification: `.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_source_pages.py -k "chat_attachment or delete_chat_session"` passed with `2` tests; `python -m compileall backend/app` passed.
- Added the root [PRODUCT.md](../PRODUCT.md) required for the UI refinement workflow and fixed two more real issues across backend and onboarding: persisted chat generation now rejects unknown `cluster_id` values before creating chat sessions/generation rows, and the onboarding route now uses its own internal scroll shell plus a pinned action footer instead of a full-screen `overflow-hidden` layout that could trap taller first-run steps inside the Electron window. Added focused regression coverage for the invalid-cluster persisted-chat path and a source-contract regression for the onboarding scroll shell. Verification: `.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_additional_qa_cases.py -k "unknown_cluster_before_creating_session or onboarding_route_uses_internal_scroll_shell or packaging_scripts_stage_local_ocr_runtime"` passed with `3` tests; `python -m compileall backend/app` passed. A TypeScript check still reports unrelated pre-existing frontend type errors outside onboarding in chat, clusters, search, and settings routes.
- Fixed two more real packaging/supportability issues in the current code path: the diagnostics bundle now includes the Electron packaged-launch logs (`desktop-runtime.log`, `backend-stdout.log`, `backend-stderr.log`) whenever `CML_STARTUP_STATUS_PATH` points into the packaged user-data directory, and the optional embedding-runtime packaging path no longer tries to run `pip` after the staged backend runtime has already been optimized and stripped of packaging tooling. The optional embedding package is now part of the backend-runtime fingerprint/package set itself, so cache hits and cache misses behave consistently. Also corrected stale packaging docs that still described the old missing-resources package failure as current state. Verification: `.\.venv\Scripts\python.exe -m unittest backend.tests.test_runtime_contracts -v` passed with `7` tests; `.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_additional_qa_cases.py -k packaging_scripts_stage_local_ocr_runtime` passed with `1` test; `python -m compileall backend/app` passed.
- Fixed a real chat pagination bug in the history/retention path: message paging sorted by `(created_at, id)` but the cursor only stored `created_at`, so sessions with multiple messages sharing the same timestamp could duplicate or skip messages across pages. Pagination now uses a composite cursor of timestamp plus message id, while still accepting the old timestamp-only cursor format for compatibility. Verification: `.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_system_vault_lock_and_embeddings.py -k "chat_pagination or chat_evidence_retention"` passed with `3` tests; `python -m compileall backend/app` passed.
- Fixed a real Bridge client-lifecycle bug in the approved-client edit path: changing an approved client's allowed vault/cluster scope could rewrite `approval_vault_id`, which is also the anchor used to load that client's encrypted identity metadata. In practice, a normal admin scope edit could make an approved client appear to lose its executable/signature identity fields. Approved clients now keep their original vault anchor after later scope edits, so identity metadata remains readable while manual clients still recompute their anchor from current scope. Verification: `.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_bridge_phase10.py -k "approved_client_scope or reenabling_bridge_client or approval_request_round_trip or claimed_name"` passed with `4` tests; `.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_bridge_phase10.py` passed with `12` tests; `python -m compileall backend/app` passed.
- Fixed a real expert-lifecycle scale/UX bug in the stale-adapter path: repeated source changes could keep appending `refresh-needed` cluster expert jobs with status `queued` even though no worker ever executes that action, which would mislead operator/UI views and grow unbounded on active large vaults. `refresh-needed` markers are now recorded as completed stale-state markers, and repeated changes while a cluster is already `needs-update` update the latest marker instead of stacking more rows until a new training cycle begins. Verification: `.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_source_pages.py -k "needs_update or expert_status or expert_retrain"` passed with `4` tests; `python -m compileall backend/app` passed.
- Fixed a real watched-folder reconciliation bug that would have corrupted normal user imports: identical files in the same synced folder were able to collapse into one source because integration imports inherited the generic checksum-dedupe rule, and checksum-only matches could also be misread as moves too early. Local folder reconciliation now treats checksum-only matches as moves only when the old path is actually gone, and integration-created file sources bypass the generic checksum dedupe while still preserving checksum metadata for later update/move detection. Verification: `.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_source_pages.py -k "duplicate_source_checksum_returns_existing_source or integration_refresh"` passed with `5` tests; `.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_reconciliation_phase12.py backend/tests/test_source_pages.py -k "integration or reconciliation"` passed with `12` tests; `python -m compileall backend/app` passed.
- Fixed two more real backend/operator issues that would have shown up under normal user-scale behavior: first-run readiness no longer deep-probes and loads the SentenceTransformers model just to answer a setup-status request, and local-model discovery now has explicit cache regression coverage so repeated readiness/discovery calls do not keep rescanning the same model roots until a refresh is requested. Also removed machine-specific defaults from backend benchmark/smoke scripts so contributors are not forced onto `T:` or a specific user profile path. Verification: `.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_additional_qa_cases.py -k "readiness or discover"` passed with `5` tests; `.\.venv\Scripts\python.exe -m pytest -q backend/tests/test_runtime_contracts.py backend/tests/test_system_vault_lock_and_embeddings.py -k "first_run_readiness or diagnostics_bundle_skips_deep_embedding_probe"` passed with `2` tests; `python -m compileall backend/app` passed.

- Completed a full backend corpus verification pass after the latest startup/chat fixes: `.\.venv\Scripts\python -m pytest -q backend/tests` now passes with `290 passed, 2 skipped` in about six minutes. Along the way, fixed two more real chat-routing regressions the broad suite exposed: plain retrieval synthesis no longer injects an empty `expert_assist` kwarg into grounded-answer call sites, and cluster-scoped expert assist now remains eligible when a cluster has an active ready adapter but has been downgraded to `needs-update` after source changes. Verification: `.\.venv\Scripts\python -m pytest -q backend/tests/test_retrieval_trust_phase8.py -k mixed_low_trust_dominant` passed; `.\.venv\Scripts\python -m pytest -q backend/tests/test_source_pages.py -k unavailable_expert_route` passed; `.\.venv\Scripts\python -m pytest -q backend/tests` passed with `290 passed, 2 skipped`.
- Fixed a real Windows vault-lock identity bug that could misclassify a live local Vault backend as an unrelated process on machines where CIM/WMI command-line inspection is denied: lock-owner classification now falls back to process-tree plus local health-listener probing instead of trusting command-line access alone, while still rejecting unrelated Python processes that merely mention backend-like argv text. Verification: `.\.venv\Scripts\python -m unittest backend.tests.test_system_vault_lock_and_embeddings.SystemVaultLockAndEmbeddingTests.test_classify_lock_owner_detects_real_uvicorn_backend backend.tests.test_system_vault_lock_and_embeddings.SystemVaultLockAndEmbeddingTests.test_classify_lock_owner_does_not_trust_backend_token_in_unrelated_process_argv -v` passed with `2` tests; `python -m compileall backend/app` passed.
- Fixed a diagnostics scale regression that could make support bundle generation hang or become unbounded on real machines: `create_diagnostic_bundle()` no longer deep-loads the SentenceTransformers embedding model just to summarize runtime state, and the runtime-contract suite now verifies that diagnostics summaries skip the heavy embedding probe while still preserving version/runtime metadata. Verification: `.\.venv\Scripts\python -m unittest backend.tests.test_runtime_contracts -v` passed with `6` tests; `python -m compileall backend/app` passed.
- Fixed three real packaged-startup/Bridge protocol regressions that broad backend tests had not covered: stale `active-vault.json` entries are now discarded so reinstall or deleted-vault scenarios route first-run users back to onboarding instead of forcing `/home`, packaged backend startup now fails as soon as the child process exits instead of waiting out the full readiness timeout, and Bridge/MCP now ignores all JSON-RPC notifications instead of replying to notification messages without an `id`. Added desktop behavior coverage for stale-vault onboarding recovery and early backend child exit, plus focused Bridge notification regression coverage. Verification: `node apps/desktop/electron/main.behavior.test.cjs` passed with `19` tests; `.venv\Scripts\python -m unittest backend.tests.test_bridge_mcp -v` passed with `4` tests; `python -m compileall backend/app` passed.
- Fixed a Bridge route contract regression introduced during scope-resolution hardening: `/api/v1/bridge/context` now resolves and validates the target vault at the Bridge boundary, so missing explicit vaults return the stable Bridge/MCP detail `vault_not_found` instead of leaking the search route's generic `"Vault not found"` message. Added focused regression coverage for the user-visible error contract. Verification: `.venv\Scripts\python.exe -m pytest -q backend/tests/test_bridge_phase10.py -k vault_not_found` passed with `1 passed, 10 deselected`; `.venv\Scripts\ruff.exe check backend` passed; `python -m compileall backend/app` passed.
- Fixed a live internal chat-persistence regression before it could turn into a hidden runtime failure: `_persist_chat_turn()` now keeps `token_budget` optional so older internal callers still complete chat generation and retrieval snapshot writes without raising a missing-argument error, and contributor docs now treat `backend/pyproject.toml` as the single backend version source instead of telling maintainers to hand-edit duplicated version strings. Verification: `.venv\Scripts\python.exe -m pytest -q backend/tests/test_source_pages.py -k persist_chat_turn` passed with `1 passed, 60 deselected`; `.venv\Scripts\ruff.exe check backend` passed; `python -m compileall backend/app` passed.
- Hardened chat/context routing with explicit synthesis token budgeting and partial-failure reporting: retrieval chat now computes a bounded local context budget, trims synthesis snippets when needed, persists snapshot `token_budget`, and reports structured `partial_failure_mode` states instead of relying on warning-string parsing. Verification: `.venv\Scripts\python.exe -m pytest -q backend/tests` passed with `283 passed, 2 skipped`; `.venv\Scripts\ruff.exe check backend` passed; `python -m compileall backend/app` passed.
- Fixed a backend/runtime audit cluster that would have caused misleading startup repair output and stale admin state: Bridge client re-enable now clears `revoked_at`, disabled Bridge client responses now reflect persisted revocation state, backend startup distinguishes `database_initialization_failed` from integrity failures, backend/MCP/diagnostics versions now resolve from `backend/pyproject.toml` instead of hardcoded strings, and chat transcript sources now persist as explicit `chat_transcript` records while session deletion still cleans legacy transcript-note rows. Verification: `.venv\Scripts\python.exe -m pytest -q backend/tests` passed with `281 passed, 2 skipped`; `.venv\Scripts\ruff.exe check backend` passed; `python -m compileall backend/app` passed.
- Phase 5 validation reconciliation: fixed exact semantic search to honor the active vector-index policy selector, hardened retrieval benchmark report output, hardened the CI-only LoRA expert smoke to drain queued indexing/training jobs, generated Phase 5 benchmark/package/expert evidence, and verified `.venv\Scripts\python.exe -m pytest -q backend/tests` with `260 passed, 3 skipped`.
- Phase 5 retrieval evidence: `scripts/backend/benchmark-1k-vault.ps1 -ReportRoot .tmp\phase5-retrieval-1k -Sources 1000` passed with `1.7232s` indexing, `0.4679s` max query latency, `0.0521s` compaction, `20,692,992` database bytes, `3` fixtures, and `15` passing threshold rows.
- Phase 5 expert evidence: `scripts/backend/smoke-lora-expert.ps1 -AllowTestTrainer -ReportPath .tmp\phase5-lora-expert-scaffold-report.json` passed with one CI scaffold adapter, runtime dependency imports available, and `training_ready`; real public LoRA remains blocked without `CML_LORA_TRAINER_COMMAND` and a real accepted base model.
- Phase 5 package evidence: `scripts/packaging/validate-clean-machine-package.ps1` and `scripts/packaging/smoke-packaged-runtime.ps1` fail against current `apps/desktop/release/win-unpacked` because packaged runtime resources are absent. Treat current package artifacts as incomplete until rebuilt/restaged.
- Added local-only security build specs for public V1: security architecture, unlock state machine, derived-state/migration rules, and the full security patch build plan; updated tracked project context and threat-model language with approved security decisions.
- Completed Security Phase 0 baseline audit: route classifications, renderer raw-HTML audit, helper executable/runtime-writable directory map, ingestion/parser/browser surface list, and security build-freeze rule are written in a local-only ignored document.
- Completed Security Phase 1 crypto and vault metadata foundation: added compact vault security metadata schema/migration, Argon2id wrapping primitives, offline recovery-key unlock/reset, sensitive-action passphrase verification, redacted public metadata, process-memory-only key state, and focused backend tests.
- Completed Security Phase 2 unlock state machine and API gating: protected routes reject until `ready`, unlock/recovery/lock/settings/sensitive-action endpoints exist, secured-vault restart returns locked, vault-bound jobs pause while locked, and Settings exposes convenience/strict/PIN controls.
- Completed Security Phase 3 encrypted storage and blob boundary: secured-vault source/page/chunk text now lands in encrypted content records instead of plaintext columns, search/training/indexing decrypt only while unlocked, large blobs stream into encrypted chunked files, diagnostics redact passphrase/recovery material, storage accounting reports encrypted footprint, and backend tests cover offline plaintext inspection.
- Completed Security Phase 4 derived-state tuple and publication framework: chunk rows and retrieval snapshots now carry normalization/extraction/embedding/index/epoch metadata, query paths snapshot the active tuple before retrieval, stale tuple chunks are excluded, staged publication records verify before atomic tuple flip, rollback restores the previous verified tuple, and regression tests cover tuple races/failures.
- Completed Security Phase 5 migration planner, disk preflight, and staging GC: planned tuple migrations estimate coexistence storage, refuse before publication when disk preflight fails, preserve the old tuple on mid-migration failure, expose bounded staging summaries/GC, include staging counts in diagnostics, and regression tests cover disk-full and GC safety.
- Completed Security Phase 6 quarantine, structural validation, and parser worker isolation: local file ingestion creates quarantine records, rejects symlinks/reparse points/unsupported types/oversized files/container bombs before parsing, stores encrypted quarantine blobs for secured vaults, parses through a subprocess worker with parent-side caps, records Defender as advisory, and persists source trust/provenance metadata.
- Completed Security Phase 7 Playwright/link isolation: dynamic browser extraction now runs in an isolated subprocess worker, validates every requested URL against public-network rules, disables downloads, enforces time/request/output budgets, preserves static HTTP-first behavior, and stores browser-derived sources as low-trust with `lora_excluded` labels.
- Completed Security Phase 8 retrieval trust gate and prompt safety: semantic search and chat retrieval now carry trust metadata, penalize low-trust candidates, classify the final evidence set before synthesis, refuse sensitive low-trust-only answers, avoid synthesis for all-low-trust evidence, cap low-trust mixed synthesis input, expose trust warnings/coverage, and quote evidence in LLM prompts.
- Completed Security Phase 9 renderer hardening: app model/document output paths render through escaped text nodes, raw HTML sinks are blocked by `npm run security:renderer`, the chart style sink remains the only sanitizer-guarded allowlist, hostile HTML/markdown fixtures stay inert, and packaged renderer responses carry CSP, `nosniff`, and `no-referrer` headers.
- Completed Security Phase 10 Bridge approval and identity: secured Bridge runtime now requires approved client tokens instead of the shared token, public approval requests/polling are time-bounded and rate-limited, admin review/rejection stays behind the local API token, approval/client/audit metadata uses encrypted storage when vault security is active, Bridge UI shows claimed-vs-observed identity signals, revocation blocks future calls, and bounded Bridge request/audit/usage history is recorded for scale.
- Completed Security Phase 13 packaging and runtime hardening: packaged startup now verifies a helper hash manifest before backend launch, audits helper-load paths against writable runtime roots, launches packaged helpers only by absolute path, constrains packaged backend child `PATH`/Python environment, ships helper-manifest/package-layout audit tooling, and fails closed on helper/runtime mismatches.
- Completed Security Phase 14 end-to-end security QA: added reproducible clean-vault, large-vault, interrupted-flow, and offline-at-rest security smokes plus a combined `scripts/security/run-security-e2e.ps1` runner; the current measured pass imported/indexed/retrieved `1200` documents with completed reconciliation, verified Bridge approval/revocation under lock/unlock rules, and found zero plaintext marker leaks in the secured-vault data directory.
- Completed turbovec Phase A and B for retrieval scale: [backend/app/core/turbovec_runtime.py](../backend/app/core/turbovec_runtime.py) now provides the vector-backend abstraction, live semantic-search routing, sidecar build/status/repair flows, incremental reindex/delete updates, manifest path/schema validation, exact-scan fail-closed behavior, and startup-repair integration; [backend/tests/test_turbovec_runtime.py](../backend/tests/test_turbovec_runtime.py) adds regression coverage for published-sidecar search, corrupt-manifest fallback, startup repair rebuilds, sidecar management routes, and source-deletion updates. Initial benchmark evidence remains the same: an 8-PDF real-corpus run produced 37 chunks and showed `6.758 ms` average current search-only latency versus `0.166 ms` for a 4-bit turbovec prototype, with `0.9583` average overlap@8, while a replicated 100K-chunk stress pass measured the current Python exact-scan path at roughly `9.8-19.5 s` search-only per query versus `3.4-11.7 ms` for the turbovec prototype.
- Verification for the turbovec Phase A/B pass: `.venv\Scripts\python -m unittest backend.tests.test_turbovec_runtime backend.tests.test_turbovec_benchmark backend.tests.test_system_vault_lock_and_embeddings -v` ran `72` tests and passed; `git diff --check` passed with whitespace warnings only from existing CRLF normalization behavior.
- Implemented the first dual-model setup pass: active chat/expert model roles in the registry, role-aware activation APIs, pair-aware onboarding/settings wording, retrieval-as-citation-authority wording, and role-aware readiness checks.
- Hotfixed mixed-embedding correctness across core retrieval paths: semantic search, scoring ledger, expanded analysis, and cluster suggestion reads now filter by the active embedding model and index version instead of silently mixing vector spaces.
- Updated security documentation to explicitly accept and document the current dynamic-link browser fallback risk and the trusted-client Bridge exfiltration boundary instead of implying stronger hardening than the code currently provides.
- Implemented the approved-model contract end to end: backend model compatibility reports, custom checkpoint import, active-model selection, readiness gating, expert-training base-model selection, onboarding/settings accepted-or-rejected model flows, bundled expert runtime packaging, and focused regression coverage.
- Continued the compulsory cluster expert build pass: added unique-source and duplicate-ratio dataset gates, minimum quality-delta config, deterministic expert evaluation harness, repeatable LoRA expert/runtime smoke scripts, strict LoRA MVP policy doc, and a backend-backed cluster Expert tab.
- Started the compulsory cluster expert build pass: added stricter LoRA graduation gates for source count, estimated token count, validation records, adapter validation, runtime-load contract metadata, stale active-adapter detection, richer failure codes, and `/api/v1/clusters/{cluster_id}/expert/status`.
- Updated cluster expert UI status mapping so backend states render as `Searchable now`, `Learning`, `Ready`, `Needs update`, or `Issue` instead of falling back to `Setting up`.
- Expert validation for this pass: focused backend/source tests ran 102 OK with 1 skipped; full backend discovery ran 178 OK with 1 skipped; `ruff check backend` passed; `npm run lint` passed with existing warnings only; `npm run build` passed.
- Added `docs/UI_ARCHITECTURE.md` as the detailed UI source of truth covering visual style, color tokens, tab requirements, component contracts, cross-cutting states, accessibility, responsive desktop behavior, and public V1 UI gates.
- Completed the full post-review implementation pass: atomic background job claiming, concurrent `/jobs/run-once` tests, fail-closed local API auth, authenticated backend identity handshake for Electron/frontend probes, FastAPI lifespan migration, shell-free LoRA trainer execution, Windows-path trainer tests, Ruff cleanup, split desktop lint scope, and packaged Windows validation.
- Current package artifacts: `apps/desktop/release/win-unpacked` and `apps/desktop/release/CML-0.1.0-Setup.exe` exist, but the current unpacked package is not release-valid because required packaged resources are missing.
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
- Model policy is now explicit: single approved family contract, current Qwen/Phi/Gemma defaults remain the default choices, and custom models are only accepted or rejected after compatibility validation.
- Q100 from the devil's advocate review is non-actionable per user instruction; do not use it to drive project decisions.
- User-facing "trained expert" language is allowed only after real adapter graduation.
- No package rebuild or VM run unless explicitly requested. Packaging triage should use the current packaged-app/runtime evidence, not assume the older missing-resource state is still the active failure.
- No UI implementation unless explicitly requested; dark version and minimized/narrow desktop version are noted future requirements.
- Do not delete or alter `UI-ref/`.
- Playwright browser runtime for local dynamic-link smoke is installed on `T:\CML-playwright-browsers`; the packaged app now also stages `resources/ms-playwright`; contributor backend requirements include `playwright==1.60.0`.
- Convenience mode is the default public-V1 unlock mode; strict locked mode remains opt-in and must stay explicit in Settings and onboarding copy.
- The optional 6-digit PIN is convenience-only and must never be treated as the primary vault security boundary; sensitive operations still require the full passphrase.
- Scale is a hard requirement for the security work: migrations, verification, trust gating, reconciliation logging, and cleanup must stay incremental, resumable, and bounded on long-lived vaults with thousands of documents.
- Packaging smoke scripts clear inherited `ELECTRON_RUN_AS_NODE`; otherwise packaged Electron launches in Node mode and will not execute app startup.
- Hash embeddings are development-only and must not be a silent production fallback.
- SQLite is authoritative; vector indexes are derived and rebuildable.
- Turbovec sidecars are sensitive derived state, not harmless cache. Phase B stores them only under `<vault>/.cml/derived-artifacts/vectors`, keeps them unencrypted at rest for now, validates that manifest `tvim_path` stays inside the expected epoch directory, and fails closed to exact scan plus repair when the sidecar is missing, corrupt, stale, or unhealthy.
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
