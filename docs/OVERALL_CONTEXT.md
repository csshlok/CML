# Overall Context

Last updated: 2026-07-13

This file preserves the longer-form current state behind `docs/PROJECT_CONTEXT.md`. It should hold durable background, validation summaries, and high-signal historical notes, not stale architecture claims.

## Current Source Of Truth

- Compact operating brief: `docs/PROJECT_CONTEXT.md`
- Migration archive: `docs/LORA_TO_RAG_MIGRATION_PLAN.md`

## Architecture State

The project has completed its migration away from the LoRA cluster-expert path.

The live architecture is now RAG-only:

- retrieval is the evidence authority
- clusters are retrieval scopes with cached profile metadata
- chat and Bridge share a retrieval-first packet contract
- Odin can append bounded, snapshot-proven graph/tree context for explicit internal or external requests without exposing a permanent graph UI
- Odin synchronization runs through immutable candidate manifests and persisted discovery, structure, retrieval, activation, and cleanup jobs; active retrieval membership changes only in the activation transaction
- Odin CLI access uses desktop-approved scoped clients, a non-secret runtime descriptor, short-lived sessions, and a Windows user-protected credential helper
- Odin structure extraction uses a versioned offline registry for Python, JSON, JavaScript/TypeScript/TSX, Go, Rust, Java, C#, C, and C++
- token reduction comes from packet shaping and cache reuse, not adapter compression
- desktop setup and packaged runtime no longer expect a second expert runtime

The earlier bundle/expert-compression architecture is historical only and should not be treated as the current product contract.

## What Changed In The Migration

The migration replaced the old `retrieval + LoRA expert` direction with a single RAG stack:

- removed LoRA runtime, training, evaluation, proof, and artifact lifecycle code
- removed expert-oriented cluster statuses and replaced them with RAG-native lifecycle fields
- moved cluster refresh to indexing-driven summary/glossary refresh
- unified chat and Bridge on the same packet shape
- removed onboarding, settings, and packaging assumptions about an expert runtime
- converted the live model recommender path to chat-only compatibility logic

Current cluster metadata now centers on:

- `index_status`
- `profile_status`
- `cluster_summary`
- `cluster_glossary`
- `profile_updated_at`
- `profile_source_hash`
- `indexed_source_count`

## Validation That Passed

The migration has already been validated beyond static code changes.

Live isolated validation passed:

- `search/semantic` returned grounded hits from the seeded RAG vault
- `chat/context` returned grounded citations and retrieval fallback output
- `bridge/context` returned grounded citations and cluster profile data
- desktop screens validated against the isolated backend loaded without console errors on the checked paths

Broader regression validation passed:

- focused backend regression slice: `127 passed`
- Electron behavior tests: `42 passed`
- Complete backend suite: `497 passed`, `4 skipped`
- npm dependency audit: `0 vulnerabilities`
- desktop typecheck and production build passed after the July 13 cleanup

Scale and token-reduction validation passed:

- synthetic user corpus benchmark with `60` files passed
- retrieval benchmark with `500` sources passed
- Odin's reviewed language corpus is deterministic across three runs and preserves unsupported/malformed files for text retrieval
- the opt-in 50,000-file Odin discovery gate passed in `126.2 s` with `68.3 MiB` peak traced memory
- desktop project, Tasks, and answer-evidence interactions passed against an isolated live backend at the 1024 px minimum without page-level horizontal overflow or console errors

## Odin Project Context

Odin's scoped release implementation is complete in live code.

The active project contract now separates:

- accepted manifest freshness
- structure readiness and `active_structure_snapshot_id`
- retrieval readiness and `active_retrieval_snapshot_id`
- optional interpretation, which remains unavailable unless a future local interpretation layer is enabled

Candidate sources have no active cluster membership and use candidate-only chunk state. Discovery and structure may become visible independently, but ordinary retrieval continues to resolve through the prior active snapshot until candidate chunks and membership are activated atomically. Cancellation and interrupted-worker reconciliation preserve the prior usable index.

The canonical desktop project route loads aggregate project facts rather than all files or graph nodes. It exposes live progress, cancellation, layer status, freshness, scoped chat entry, run history, folder reconnection, cluster links, layer-specific reindex, and safe removal. Graph/tree views remain on demand. Project-grounded answer citations disclose only the evidence used by that answer, including path, line span, symbol, snapshot/commit, excerpt, and local file actions.

The remaining Odin-adjacent items are deliberate deferrals rather than incomplete promises: project interpretation, automatic watch/hooks, remote repository indexing, cross-project retrieval until its citation/freshness contract is proven, Tier C languages, and non-Windows credential helpers.

## Current Token Reduction Interpretation

The old token-reduction story depended on expert compression. That is no longer true.

The current RAG system still reduces tokens materially because it:

- selects only relevant evidence
- trims and deduplicates citations
- reuses working memory
- reuses cached cluster profile material
- benefits from warm-cache repeat-query behavior

Current benchmark evidence:

- average raw tokens: `1858.62`
- average current packet tokens: `1030.38`
- average reduction: `44.43%`
- warm-cache average reduction: `94.8%`

This is the right product story now: retrieval-driven reduction, not model-compression-driven reduction.

## Remaining Non-Migration Work

The migration is complete, but some release work remains:

- clean-machine packaged validation
- broader release hardening and security proof
- optional local synthesis runtime setup for richer final chat answers

## July 13 Product Integrity Pass

The desktop UI and repository were audited for false, stale, and developer-facing surfaces.

Changes that now define current behavior:

- Home no longer has a health/quick-action/activity right rail; Quick Actions lead into the prompt and Activity follows Suggested Clusters.
- Cluster progress uses real indexed-source ratios and all shared progress components clamp values to `0–100`.
- Settings Health shows live service, library, database, memory-search, local-chat, task, OCR, and hardware results.
- The Map route no longer accepts or substitutes seeded demo content.
- Chat no longer shows a fabricated cluster count when no library is open.
- Onboarding no longer advertises an unimplemented Google account flow.
- Production routes no longer consume seeded state or mock reply generation. The mock vault store is retained as an explicit development fixture, protected by a test that prevents production route/component imports.
- The reusable UI primitive inventory is retained for future feature work; only obsolete product-specific code remains deleted.
- A shared encrypted-source hydration bug was fixed so authorized search, memory, and report paths receive all decrypted fields without restoring plaintext database storage.
- README and live interface copy now address users directly and reserve backend/runtime terminology for advanced settings and diagnostics.
- Historical UI audit, ingestion-reference, and packaging-investigation documents are retained with status notices so their evidence remains available without being mistaken for current implementation truth.

The Odin architecture/UI/benchmark/ADR drafts remain useful local working notes but are intentionally ignored by Git. Implemented Odin behavior and release status must stay summarized in `PROJECT_CONTEXT.md`. The desktop now includes a first-class Projects navigation destination and lightweight project index; project details remain centered on status, scoped questions, and run activity, with graph/tree artifacts shown only when requested.

Important distinction:

- missing local synthesis runtime is not a migration bug
- it only means chat falls back to retrieval-draft output instead of local grounded synthesis

## Historical Note

The completed migration record remains in `docs/LORA_TO_RAG_MIGRATION_PLAN.md`. Security audit/build records may also retain LoRA references where they document historical threat analysis. Neither is a live product contract. When an archive conflicts with `docs/PROJECT_CONTEXT.md`, the project context document is authoritative.
