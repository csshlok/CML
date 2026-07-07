# LoRA to RAG Migration Plan

## Goal

Replace the current `retrieval + LoRA expert` architecture with a pure RAG architecture without breaking:

- source ingestion and indexing
- cluster-scoped retrieval
- chat grounding and citations
- Bridge context packets
- desktop setup and status flows
- vault unlock and storage accounting
- packaging and startup integrity checks

This document reflects the current codebase state as of 2026-07-07.

## Current Status

The migration is complete on the live backend, desktop, and packaging paths. The hard-removal schema migration, runtime cleanup, desktop contract cleanup, and verification work are all now finished.

Estimated remaining work: 0%.

Current branch state:

- backend RAG contract is live
- cluster lifecycle is RAG-native
- recommender live path is chat-only
- LoRA runtime modules are removed
- vault crypto no longer derives LoRA artifact keys
- Electron/package startup no longer depends on a second expert runtime
- desktop cluster lifecycle/status UI is mostly RAG-native
- cluster profile refresh no longer writes legacy `cluster_expert_jobs` rows
- the Bridge permission contract now uses `allow_cluster_profile` on the live API/UI surface
- legacy `expert_status` create-time writes have been removed from live cluster creation paths
- hard-removal DB rebuilds now strip `expert_status` and `allow_expert_calls` from upgraded databases
- hard-removal DB cleanup now drops `cluster_expert_jobs` and `expert_artifacts`
- storage accounting no longer reports `expert_artifacts`
- cluster profile metadata now persists `profile_updated_at`, `profile_source_hash`, and `indexed_source_count`
- legacy table rebuilds now use a foreign-key-safe create/copy/drop/rename pattern
- dead legacy `train_cluster_adapter` job registry/stub code is removed
- packaged desktop backend staging has been resynced to the migrated backend
- large QA files were preserved and trimmed instead of being broadly deleted
- only historical/archive planning docs still mention the old expert-compression direction; they are not live product contracts

Latest broad verification that already passed:

- `backend.tests.test_vault_crypto_phase1`
- `backend.tests.test_model_recommender`
- `backend.tests.test_bridge_mcp`
- `backend.tests.test_retrieval_trust_phase8`
- `backend.tests.test_source_pages`
- `backend.tests.test_additional_qa_cases`
- `backend.tests.test_lora_to_rag_phase12`
- `backend.tests.test_bridge_phase10`
- `backend.tests.test_browser_ingestion_phase7`
- `backend.tests.test_cluster_bundle`
- `backend.tests.test_unlock_phase2`

Verified broad command:

```powershell
.venv\Scripts\python.exe -m unittest backend.tests.test_vault_crypto_phase1 backend.tests.test_model_recommender backend.tests.test_bridge_mcp backend.tests.test_retrieval_trust_phase8 backend.tests.test_source_pages backend.tests.test_additional_qa_cases backend.tests.test_lora_to_rag_phase12 backend.tests.test_bridge_phase10 backend.tests.test_browser_ingestion_phase7 backend.tests.test_cluster_bundle backend.tests.test_unlock_phase2 -v
```

Result: `297 tests`, `OK` with `1 skipped`.

Additional focused verification from the prior completed pass:

- `backend.tests.test_model_recommender`: `19 tests`, `OK`
- `backend.tests.test_retrieval_trust_phase8`: `16 tests`, `OK`
- `backend.tests.test_additional_qa_cases`: `104 tests`, `OK` with `1 skipped`
- `backend.tests.test_lora_to_rag_phase12`: `12 tests`, `OK`
- `backend.tests.test_bridge_phase10` + `backend.tests.test_cluster_bundle`: `17 tests`, `OK`
- `npm run build --workspace @cml/desktop`: `OK`
- `apps/desktop/electron/helper-integrity.test.cjs` + `scripts/packaging/generate-helper-manifest.test.cjs`: `7 tests`, `OK`

Latest verification for the final hard-removal pass:

- `backend.tests.test_lora_to_rag_phase12`
- `backend.tests.test_bridge_phase10`
- `backend.tests.test_cluster_bundle`
- `backend.tests.test_extension_setup_contract`
- `backend.tests.test_benchmark_matrix`
- `backend.tests.test_background_jobs`
- `backend.tests.test_system_vault_lock_and_embeddings`
- `npm run build --workspace @cml/desktop`
- `apps/desktop/electron/helper-integrity.test.cjs` + `scripts/packaging/generate-helper-manifest.test.cjs`

Result:

- focused schema-sensitive backend slice: `38 tests`, `OK`
- background-job slice: `10 tests`, `OK`
- system/vault slice: `69 tests`, `OK`
- broader backend regression slice: `309 tests`, `OK` with `1 skipped`
- desktop build: `OK`
- helper integrity / manifest tests: `7 tests`, `OK`

Latest incremental cleanup in this pass:

- live cluster refresh no longer mutates `expert_status` to `expert_stale`
- live cluster refresh no longer inserts compatibility rows into `cluster_expert_jobs`
- chats/auto-created clusters now seed RAG-native lifecycle fields instead of compatibility status
- Bridge permission copy now refers to cluster profiles instead of style profiles
- the Bridge API/UI contract now uses `allow_cluster_profile` while still accepting the legacy `allow_style_profile` input alias
- the stale audit script was moved from `active_model_pair_status` to `active_chat_setup_status`
- the dead `training_evaluation.py` module and its dedicated contract test were removed
- `clusters`, `bridge_settings`, and `bridge_clients` are now rebuilt on init for old installs so retired columns are physically removed
- retired expert tables are now dropped during DB initialization
- live cluster insertion paths and storage accounting were updated to the post-compatibility schema
- schema-sensitive tests were rewritten so they no longer rely on `expert_status`, `cluster_expert_jobs`, `expert_artifacts`, or `allow_expert_calls`
- cluster profile refresh now persists `profile_updated_at`, `profile_source_hash`, and `indexed_source_count`
- cluster/profile table rebuilds now preserve foreign-key targets during old-database upgrade
- security and QA docs were updated where they still described removed LoRA-era labels or job behavior

## What Is Already Done

### Phase 1: Contract Freeze And Live Path Audit

Completed.

Implemented:

- the live bundle path is now RAG-first and no longer depends on LoRA runtime generation
- chat, Bridge, and MCP packet flows were traced and aligned around the RAG packet shape
- cluster source-change hooks were audited before lifecycle changes were made

Primary files already migrated:

- [backend/app/core/cluster_bundle.py](/T:/CML/backend/app/core/cluster_bundle.py)
- [backend/app/core/context_packets.py](/T:/CML/backend/app/core/context_packets.py)
- [backend/app/api/routes/chat.py](/T:/CML/backend/app/api/routes/chat.py)
- [backend/app/api/routes/bridge.py](/T:/CML/backend/app/api/routes/bridge.py)
- [backend/app/bridge_mcp.py](/T:/CML/backend/app/bridge_mcp.py)

### Phase 2: Additive Schema, Lifecycle, And Compatibility Work

Completed.

Implemented:

- `clusters` now carry:
  - `index_status`
  - `profile_status`
  - `cluster_summary`
  - `cluster_glossary`
  - `profile_updated_at`
  - `profile_source_hash`
  - `indexed_source_count`
- expert tables were soft-deprecated with `deprecated_at`
- source-state indexes were added for lifecycle and profile-refresh queries
- storage accounting now filters deprecated expert artifacts
- RAG lifecycle defaults are now written for new clusters and synthetic chat clusters
- source changes now mark clusters stale and schedule profile refresh work
- the live lifecycle implementation was moved to `cluster_lifecycle.py`
- live profile-refresh scheduling no longer writes compatibility rows to `cluster_expert_jobs`
- source-state query support was indexed so lifecycle/profile refresh scans stay keyed

Primary files already migrated:

- [backend/app/core/database.py](/T:/CML/backend/app/core/database.py)
- [backend/app/core/cluster_lifecycle.py](/T:/CML/backend/app/core/cluster_lifecycle.py)
- [backend/app/core/background_jobs.py](/T:/CML/backend/app/core/background_jobs.py)
- [backend/app/core/clustering.py](/T:/CML/backend/app/core/clustering.py)
- [backend/app/core/chat_memory.py](/T:/CML/backend/app/core/chat_memory.py)
- [backend/app/core/storage_accounting.py](/T:/CML/backend/app/core/storage_accounting.py)

### Phase 3: API And Runtime Cutover

Completed on the live path.

Implemented:

- cluster bundle live response path is RAG-only
- shared packet rendering no longer emits expert digest content
- chat grounded-answer live path no longer threads expert-assist state
- Bridge and MCP were cut over to the RAG-only external packet shape
- cluster expert API routes were removed
- `/system/lora-trainer` was removed
- unlock-state safe route allowances for the LoRA trainer were removed
- Bridge live logic stopped writing `allow_expert_calls`
- dead expert response models were removed from `schemas.py`
- a manual `POST /clusters/{cluster_id}/refresh-profile` route was added
- `VaultSubkeys` no longer derive or expose `lora_artifact_key`
- legacy QA suites were preserved as files but had only their LoRA-specific methods removed or rewritten
- cluster and bundle tests were rewritten around RAG-only expectations instead of adapter/trainer behavior
- the live lifecycle module import surface was switched from `expert_lifecycle.py` to `cluster_lifecycle.py`

Primary files already migrated:

- [backend/app/api/routes/chat.py](/T:/CML/backend/app/api/routes/chat.py)
- [backend/app/api/routes/bridge.py](/T:/CML/backend/app/api/routes/bridge.py)
- [backend/app/api/routes/clusters.py](/T:/CML/backend/app/api/routes/clusters.py)
- [backend/app/api/routes/system.py](/T:/CML/backend/app/api/routes/system.py)
- [backend/app/core/unlock_state.py](/T:/CML/backend/app/core/unlock_state.py)
- [backend/app/schemas.py](/T:/CML/backend/app/schemas.py)

### Phase 4: LoRA Runtime And File Deletion

Complete on the live/runtime path.

Implemented:

- LoRA-only backend settings were removed from `config.py`
- browser/writeback trust flow moved from `lora_excluded` to `external_untrusted`
- several dedicated LoRA backend modules were deleted
- several dedicated LoRA backend tests were deleted
- several dedicated LoRA backend scripts were deleted
- model recommender live catalog, scoring, fit, explanations, and service logic were reduced to chat-only semantics
- registry state no longer persists `active_expert_model_id`
- the dead recommender `pairing.py` module was removed
- Electron startup no longer requires or injects a separate expert Python runtime
- helper manifest generation and package layout audit no longer track `expert-python-runtime`
- Windows packaging no longer stages or ships `expert-python-runtime`
- packaged runtime smoke/validation scripts were updated to a single-runtime model
- desktop cluster lifecycle chips, map state, adapters, and onboarding/settings contract types were cut over toward RAG-native naming
- dead structural training-evaluation helpers were removed
- the Bridge permission contract was renamed from style-profile wording to cluster-profile wording

Deleted backend modules:

- [backend/app/core/lora_training.py](/T:/CML/backend/app/core/lora_training.py)
- [backend/app/core/training_dataset.py](/T:/CML/backend/app/core/training_dataset.py)
- [backend/app/core/expert_evaluation.py](/T:/CML/backend/app/core/expert_evaluation.py)
- [backend/app/core/expert_runtime.py](/T:/CML/backend/app/core/expert_runtime.py)
- [backend/app/core/expert_runtime_worker.py](/T:/CML/backend/app/core/expert_runtime_worker.py)
- [backend/app/core/expert_profiles.py](/T:/CML/backend/app/core/expert_profiles.py)
- [backend/app/core/external_lora_dataset.py](/T:/CML/backend/app/core/external_lora_dataset.py)
- [backend/app/core/lora_proof.py](/T:/CML/backend/app/core/lora_proof.py)
- [backend/app/core/model_recommender/pairing.py](/T:/CML/backend/app/core/model_recommender/pairing.py)

Deleted LoRA-only tests:

- [backend/tests/test_cluster_bundle_benchmark.py](/T:/CML/backend/tests/test_cluster_bundle_benchmark.py)
- [backend/tests/test_cluster_bundle_training.py](/T:/CML/backend/tests/test_cluster_bundle_training.py)
- [backend/tests/test_export_lora_run_artifacts.py](/T:/CML/backend/tests/test_export_lora_run_artifacts.py)
- [backend/tests/test_lora_proof_bundle_contract.py](/T:/CML/backend/tests/test_lora_proof_bundle_contract.py)

Deleted LoRA-only scripts:

- [scripts/backend/benchmark-lora-adapter.ps1](/T:/CML/scripts/backend/benchmark-lora-adapter.ps1)
- [scripts/backend/export-cluster-lora-dataset.py](/T:/CML/scripts/backend/export-cluster-lora-dataset.py)
- [scripts/backend/export-lora-proof.ps1](/T:/CML/scripts/backend/export-lora-proof.ps1)
- [scripts/backend/export-path-text-lora-dataset.py](/T:/CML/scripts/backend/export-path-text-lora-dataset.py)
- [scripts/backend/import-hf-wikipedia-squad.py](/T:/CML/scripts/backend/import-hf-wikipedia-squad.py)
- [scripts/backend/run-imported-lora-retrain.py](/T:/CML/scripts/backend/run-imported-lora-retrain.py)
- [scripts/backend/smoke-lora-expert.ps1](/T:/CML/scripts/backend/smoke-lora-expert.ps1)
- [scripts/backend/smoke-lora-runtime.ps1](/T:/CML/scripts/backend/smoke-lora-runtime.ps1)

### Phase 5: Validation And One-Release Compatibility Cleanup

Completed.

Implemented in this phase already:

- DB initialization now rebuilds `clusters` to physically remove legacy `expert_status` on upgraded installs
- DB initialization now rebuilds `bridge_settings` and `bridge_clients` to physically remove legacy `allow_expert_calls`
- DB initialization now drops `cluster_expert_jobs` and `expert_artifacts`
- live cluster creation paths no longer write `expert_status`
- storage accounting no longer queries or reports `expert_artifacts`
- schema-sensitive tests were updated to the hard-removal schema
- cluster profile metadata now persists `profile_updated_at`, `profile_source_hash`, and `indexed_source_count`
- legacy schema rebuilds now preserve foreign-key targets correctly during upgrade
- stale QA/security references tied to removed LoRA-era behavior were updated
- final broader verification slices passed on backend, desktop, and packaging helpers

## Key Decisions Already Locked In

These decisions are already reflected in the live migration work and should not be reopened unless the architecture changes again.

### Cluster Metadata Contract

Clusters are now migrating toward a RAG-native metadata shape:

- `index_status`
- `profile_status`
- `cluster_summary`
- `cluster_glossary`
- `profile_updated_at`
- `profile_source_hash`
- `indexed_source_count`

`expert_status` is no longer the architectural center.

### Shared Packet Contract

The shared packet contract is RAG-only.

Kept:

- citations
- source snippets
- expansion handles
- memory
- working memory
- bundle status
- token estimate
- retrieval authority

Removed from the live contract:

- `expert_digest`
- `expert_used`
- `expert_mode`
- LoRA-specific token accounting fields

### Lifecycle Model

The cluster state model is split:

- `index_status`: retrieval availability
- `profile_status`: cached profile freshness

This is the right separation because indexing and profile-refresh are independent operations.

### Bridge Permissions

Live logic now treats Bridge permissions as:

- keep `allow_raw_snippets`
- keep profile-style gating
- stop using `allow_expert_calls`

The live API/UI field is `allow_cluster_profile`. The persisted SQLite column is still `allow_style_profile` for now, but `allow_expert_calls` is no longer part of the schema.

## Blockers And Residual Risks

### Blocker 1: `vault_crypto.py` `lora_artifact_key`

Status: completed.

Completed work:

1. audited remaining `lora_artifact_key` reads
2. removed the dataclass field
3. removed the derivation branch
4. updated vault-crypto tests
5. re-verified unlock-oriented tests

### Blocker 2: Desktop Packaging Required The Expert Runtime

Status: completed.

Completed work:

1. removed `expertRuntime` and `expertPython` from integrity requirements
2. updated manifest generation tests
3. removed expert-runtime packaging from Windows packaging scripts
4. updated packaged runtime smoke and validation scripts
5. verified Electron/package tests on the current branch

### Blocker 3: Recommender Internals Carried Pair/Expert Semantics

Status: completed on the live path.

Completed work:

1. kept `pairing.py` deleted and removed live references to it
2. removed pair/expert-only scoring and fit branches from the live recommender path
3. collapsed live activation and recommendation payloads to chat-only semantics
4. updated recommender tests around the chat-only live product model

Residual note:

1. historical planning/context docs may still describe the older expert-compression direction, but live recommender code and tests are chat-only

### Blocker 4: Desktop Wording And Type Drift

Status: completed on the live path.

Completed work:

1. cluster mock/store state was moved from expert-centric labels to lifecycle-centric labels
2. cluster chips, map UI, adapters, and cluster detail views now read RAG-native lifecycle state
3. onboarding and settings contract types were updated away from `active_pair` and `pairing_detail`
4. Bridge permission copy now talks about cluster profiles instead of style profiles
5. the Bridge API/UI contract now uses `allow_cluster_profile`
6. local desktop build and package/integrity tests still pass after the contract changes

Residual note:

1. only historical planning/context docs may still mention the old expert-runtime direction

### Blocker 5: Mixed Legacy Test Suites Asserted Old LoRA Behavior

Status: completed.

Handled in the current branch:

- [backend/tests/test_additional_qa_cases.py](/T:/CML/backend/tests/test_additional_qa_cases.py)
- [backend/tests/test_source_pages.py](/T:/CML/backend/tests/test_source_pages.py)
- [backend/tests/test_bridge_mcp.py](/T:/CML/backend/tests/test_bridge_mcp.py)
- [backend/tests/test_retrieval_trust_phase8.py](/T:/CML/backend/tests/test_retrieval_trust_phase8.py)
- [backend/tests/test_vault_crypto_phase1.py](/T:/CML/backend/tests/test_vault_crypto_phase1.py)
- [backend/tests/test_model_recommender.py](/T:/CML/backend/tests/test_model_recommender.py)
- [backend/tests/test_lora_to_rag_phase12.py](/T:/CML/backend/tests/test_lora_to_rag_phase12.py)

Completed closeout:

1. broad QA suites were preserved
2. affected methods were rewritten around RAG-only behavior
3. focused old-database upgrade coverage was added for the hard-removal schema path

### Blocker 6: Compatibility Naming Still Exists In Live Backend Helpers

Status: completed for live code.

Files still needing final attention:

- [backend/app/core/cluster_lifecycle.py](/T:/CML/backend/app/core/cluster_lifecycle.py)
- [backend/app/core/background_jobs.py](/T:/CML/backend/app/core/background_jobs.py)
- [backend/app/core/database.py](/T:/CML/backend/app/core/database.py)
- [backend/app/api/routes/clusters.py](/T:/CML/backend/app/api/routes/clusters.py)
- [backend/app/core/chat_memory.py](/T:/CML/backend/app/core/chat_memory.py)

Completed work:

1. removed the live `expert_assist` path from chat and `llm_runtime`
2. replaced the live lifecycle module with `cluster_lifecycle.py`
3. changed background job scope handling from `expert` to `cluster`
4. stopped writing legacy `cluster_expert_jobs` rows from live profile refreshes
5. updated targeted tests around the new lifecycle/runtime behavior

Residual note:

1. remaining occurrences are limited to migration helpers, test fixtures that model legacy DBs, or historical documentation

## Detailed Work Remaining By Phase

### Remaining Phase 3 Work

Completed.

Exit evidence:

- no live UI screen asks the user to configure or reason about an expert runtime
- no live route emits expert-era contract fields
- targeted cluster/chat/Bridge tests and desktop build all passed

### Remaining Phase 4 Work

Completed.

Exit evidence:

- app boot, chat, Bridge, onboarding, and unlock all work with no expert runtime files present
- packaging does not require expert helpers
- desktop build and helper integrity / manifest tests passed
- broad backend regression passed without LoRA-only failures

### Remaining Phase 5 Work

Completed.

Exit evidence:

1. focused backend slices against the rebuilt schema path passed
2. desktop/package verification passed
3. explicit old-database upgrade coverage was added and passed
4. stale QA/security references were cleaned up where they described active product behavior
5. final repo-wide residue scan shows live-path code is clean; remaining occurrences are limited to migration helpers, legacy-schema test fixtures, staging copies generated from migrated backend code, or historical documentation

## Concrete Next Execution Order

Execution is complete.

Final verification commands that passed:

```powershell
.venv\Scripts\python.exe -m unittest backend.tests.test_lora_to_rag_phase12 backend.tests.test_bridge_phase10 backend.tests.test_cluster_bundle backend.tests.test_extension_setup_contract backend.tests.test_benchmark_matrix -v
.venv\Scripts\python.exe -m unittest backend.tests.test_background_jobs -v
.venv\Scripts\python.exe -m unittest backend.tests.test_system_vault_lock_and_embeddings -v
.venv\Scripts\python.exe -m unittest backend.tests.test_vault_crypto_phase1 backend.tests.test_model_recommender backend.tests.test_bridge_mcp backend.tests.test_retrieval_trust_phase8 backend.tests.test_source_pages backend.tests.test_additional_qa_cases backend.tests.test_lora_to_rag_phase12 backend.tests.test_bridge_phase10 backend.tests.test_browser_ingestion_phase7 backend.tests.test_cluster_bundle backend.tests.test_unlock_phase2 backend.tests.test_background_jobs -v
npm run build --workspace @cml/desktop
node --test apps/desktop/electron/helper-integrity.test.cjs scripts/packaging/generate-helper-manifest.test.cjs
```

## Detailed Work Left

### Backend Remaining

No live backend migration work remains.

### Desktop Remaining

No live desktop migration work remains.

### Tests Remaining

No migration-blocking test work remains. Broad QA files were preserved and the affected assertions were updated in place.

## Cluster Update Behavior After New Files Are Added

This is the operational model the migration is preserving.

### Target Behavior

When a new file is added to a cluster:

1. the cluster is marked stale immediately
2. if indexing is needed, `index_status` becomes `indexing`
3. retrieval continues using the last good indexed corpus when possible
4. once indexing finishes, profile refresh is enqueued
5. profile refresh recomputes:
   - `cluster_summary`
   - `cluster_glossary`
   - `indexed_source_count`
   - `profile_source_hash`
   - `profile_updated_at`
6. `profile_status` returns to `ready`
7. if indexed sources exist, `index_status` returns to `ready`

### Why This Is Safe

- retrieval does not wait on profile recomputation
- cluster usability is no longer blocked on training
- new files improve cluster context through indexing plus profile refresh
- cached profile metadata is treated as derived support data, not as the source of truth

## High-Risk Files Still Requiring Final Attention

None for the migration itself. The main remaining references to the retired architecture are historical documentation and legacy-schema test fixtures.

## Summary

The migration is complete. The backend RAG contract, lifecycle model, recommender live path cleanup, vault crypto cleanup, package/runtime cleanup, hard-removal schema path, desktop contract cleanup, packaging sync, and verification work are all finished.

Remaining mentions of the old expert-compression direction are limited to historical planning/context documents and deliberate legacy-schema test fixtures. They are no longer part of the live product path.
