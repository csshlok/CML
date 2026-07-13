# Project Context And Progress

Last updated: 2026-07-13

## Operating Rule

This is the compact source of truth for the project. Keep it current and small.

- Prefer current truth over historical logs.
- Move deep implementation detail to dedicated design docs.
- Long-form fallback: `docs/OVERALL_CONTEXT.md`.
- Current migration record: `docs/LORA_TO_RAG_MIGRATION_PLAN.md`.

## Project Goal

Build CML, a local-first Windows desktop app for turning a user's files, notes, links, screenshots, transcripts, and synced folders into reusable, grounded AI context.

CML is not just a vault UI. It is a context-management layer between the user and LLMs:

- preserve long-lived context outside the model
- reduce repeated transcript and corpus replay
- return grounded context packets instead of raw dumps
- let internal chat and external tools reuse the same local context through Bridge, MCP, CLI, and API

## Current Product Decisions

- Product form: local downloadable desktop app, not a hosted web app.
- Public V1 platform: Windows only.
- Desktop shell: Electron in `apps/desktop`.
- Backend: FastAPI in `backend`.
- Browser extension: thin capture surface for Chrome and Brave.
- V1 storage: explicit local vaults only.
- Vault layout: `CML_DATA_DIR=<vault>/.vault` and `CML_DATABASE_PATH=<vault>/.vault/cml.sqlite3`.
- First-class external surfaces: Bridge, MCP, local HTTP API, CLI.
- Local-first privacy remains a release requirement.
- Security boundary remains a release requirement: vault unlock, encryption, Bridge approval, parser/browser isolation, renderer hardening, and package integrity.

Odin currently provides project registration, idempotent sync, snapshots, project-backed clusters, source reconciliation, structural nodes/edges, possible-relationship records, bounded graph queries and graph/tree exports, project-scoped chat/context, optional Bridge graph packets, CLI CRUD/explain/path/context/graph/tree commands, and the primary desktop project workspace. Its inline graph/tree component is mounted only after an explicit project-scoped visualization request. It never writes to the registered repository.

Odin architecture, UI exploration, and benchmark notes are local working documents and are intentionally ignored by Git. Current repository truth is captured here and in the implemented code under `backend/app/core/projects.py`, `backend/app/core/project_graph.py`, `backend/app/api/routes/projects.py`, and the desktop project workspace.

Odin is not release-complete. Scoped CLI device authentication, asynchronous cancellable sync with fully atomic staging, broad tree-sitter language coverage, interpretation briefs, and several secondary UI surfaces remain open gates.

## Current Architecture

The LoRA cluster-expert direction has been removed from the live product.

CML is now RAG-only:

- retrieval is the authority for facts, citations, source IDs, dates, names, numbers, and missing-evidence refusal
- clusters provide cached profile metadata to improve packet quality, not a trained expert layer
- chat and Bridge both consume the same retrieval-first context contract
- token reduction comes from packet shaping, citation selection, memory distillation, and cache reuse

The current cluster contract is:

```text
Cluster =
  retrieval scope
  cached summary
  cached glossary
  profile freshness metadata
  index/profile status
```

Current cluster lifecycle fields:

- `index_status`: `empty`, `indexing`, `ready`, `stale`, `error`
- `profile_status`: refresh state for cached profile material
- `cluster_summary`
- `cluster_glossary`
- `profile_updated_at`
- `profile_source_hash`
- `indexed_source_count`

## Current RAG Contract

Shared context delivery is now retrieval-first across chat and Bridge:

- selected clusters
- citations
- source snippets
- memory items
- working memory
- cluster profile
- token estimate
- bundle status
- warnings

Removed from the live path:

- LoRA runtime and training
- expert-compression packets
- expert artifact activation/rollback
- adapter quality gates
- expert-only setup/runtime flows

## What Is Done

The LoRA-to-RAG migration is complete in live code:

- backend schema and lifecycle are RAG-native
- cluster refresh happens from indexing/profile jobs
- chat uses retrieval-first packets
- Bridge uses retrieval-first packets
- desktop cluster, source, Bridge, onboarding, and settings flows are aligned with RAG
- packaged desktop startup no longer depends on an expert runtime
- model recommender live path is chat-only
- LoRA runtime, training, and proof modules are removed

The July 13 UI integrity pass also completed:

- Home now uses one main column, with Quick Actions above the prompt and Activity below Suggested Clusters
- Suggested Cluster counts and progress come from real indexed sources and cannot overflow their cards
- Settings includes a live Health section backed by backend, library, database, embedding, model, job, OCR, and hardware checks
- production Map no longer exposes seeded demo data
- Chat no longer fabricates a cluster count when no library is open
- unimplemented Google sign-in surfaces were removed; onboarding now explains the local profile directly
- production routes no longer depend on seeded state; the mock vault store remains available as a guarded development and interaction-test fixture
- the reusable UI primitive inventory and its required packages are retained for feature work even when individual primitives are not mounted today
- stale LoRA runtime code and dependencies with no live product role were removed
- secured-source hydration now restores every encrypted content field for authorized in-memory readers while keeping plaintext database columns empty

Authoritative migration record:

- `docs/LORA_TO_RAG_MIGRATION_PLAN.md`

## Current Validation Status

Latest repo-backed validation that already passed:

- live isolated backend search returned grounded citations
- live isolated `chat/context` returned grounded citations and retrieval fallback output
- live isolated `bridge/context` returned grounded citations and cluster profile data
- desktop frontend loaded against the isolated backend without console errors on the validated screens
- backend regression slice: `127 passed`
- synthetic mixed-corpus benchmark: passed
- retrieval benchmark at `500` sources: passed
- Odin targeted tests: `6 passed`
- desktop production typecheck/build: passed on 2026-07-13
- Electron behavior tests: `37 passed`
- encrypted storage regression tests: `7 passed`
- complete backend suite: `471 passed`, `3 skipped` on 2026-07-13
- root `pytest` discovery is scoped to `backend/tests` so packaged runtimes, releases, and local comparison clones are not collected
- npm dependency audit: `0 vulnerabilities` after compatible lockfile updates
- primary Electron routes: no visible overflow at the supported 1024 px minimum and at 1440 px
- Odin structural benchmark on this repo: ready, 353 files, 3,740 nodes, 7,498 authoritative edges; 2.47 s median cold wall time
- Graphify 0.9.13 pinned comparison: completed; see the benchmark document

## Current Token Reduction Story

Token reduction still exists, but it is now retrieval-driven instead of LoRA-driven.

Current benchmark evidence:

- average raw tokens: `1858.62`
- average current packet tokens: `1030.38`
- average reduction: `44.43%`
- warm-cache average reduction: `94.8%`

Reduction now comes from:

- relevance filtering
- citation deduplication
- snippet trimming
- working-memory reuse
- cached cluster profile material
- packet shaping for repeat queries

## Current Caveats

- If no local synthesis runtime is configured, chat falls back to retrieval-draft output. That is expected and not a RAG failure.
- Clean-VM and full packaged release validation remain release tasks, separate from the migration itself.

## Current Progress

| Area | State | Notes |
| --- | --- | --- |
| Core RAG migration | Complete | Live backend, desktop, and packaging paths are RAG-only. |
| Bridge/MCP context delivery | Complete | Shared retrieval-first packet contract is live. |
| Cluster lifecycle/profile refresh | Complete | Indexing and cached profile refresh are live. |
| Model recommender migration | Complete for live path | Chat-only live path is in place; no expert-role dependency remains. |
| Token reduction | Complete for RAG V1 | Packet shaping and cache reuse are producing measurable reduction. |
| Release hardening | In progress | Packaging, security, and clean-machine proof remain release work. |
| Odin project context | Foundation implemented, release gates open | Structural graph, retrieval integration, CLI commands, and core UI are live; auth/jobs/coverage/supporting UI remain. |
| UI truth and copy | Current pass complete | Hardcoded health/demo/count surfaces removed; active app copy uses user-facing language by default. |

## Immediate Next Steps

1. Complete Odin CLI device authentication and scoped authorization.
2. Move Odin sync to cancellable background jobs with atomic candidate activation.
3. Expand deterministic parser coverage and finish supporting project UI surfaces.
4. Continue release hardening, accessibility QA, and clean-machine proof.
