# CML Product Requirements Document

Last updated: 2026-06-17

## 1. Executive Summary

CML is a Windows-first local desktop product for turning personal files, links, notes, screenshots, transcripts, and synced folders into reusable AI context.

The core job is not generic file search. The product is a context-management layer between the user and an LLM:

- preserve long-lived context outside the model
- reduce repeated transcript and corpus replay
- return grounded context packets instead of raw dumps
- let external AI tools use the same local memory through Bridge, MCP, CLI, and API

Public V1 is a downloadable Windows desktop app with three connected surfaces:

- Electron desktop app for onboarding, capture, search, chat, map, settings, and Bridge management
- FastAPI local backend for ingestion, retrieval, clustering, memory, model setup, and local APIs
- Chromium browser extension for thin capture flows into the active vault

The product promise is local-first, source-grounded, inspectable context reuse.

## 1.1 Intended Impact

If CML succeeds, it should change the user workflow in three concrete ways:

- users stop replaying the same corpus and old chat history into every session
- external AI tools can ask for compact local context instead of raw source dumps
- grounded answers become faster to resume across long-running or interrupted work

The intended user impact is lower token spend, lower context-loss risk, and higher answer trust because evidence stays attached to the response path.

## 1.2 Measured Impact So Far

Current repo-backed benchmark evidence already shows meaningful context compression and scale improvements:

- synthetic mixed-corpus benchmark: `41.84%` average first-turn reduction and `94.05%` warm-cache reduction across 15 generated files
- large synthetic 10k-file benchmark: `33.59%` average first-turn reduction and `93.36%` warm-cache reduction across 10,000 sources
- broader context-layer benchmark: `24.06%` average packet savings across 120 sources / 12 clusters
- broader adversarial context-layer benchmark: `27.17%` average packet savings across 240 sources / 24 clusters while still downgrading hostile evidence
- capped real-vault benchmark: query p95 improved from `10172.38 ms` to `228.85 ms` after the exact-search scale fix, and the later stabilized run finished at `313.74 ms` query p95 with `400/400` imports successful

These numbers support the claim that CML is already more than a simple vault UI: it is producing measurable context reduction and retrieval-performance gains.

## 1.3 Predictive V1 Impact

The following are forecasted product outcomes, not yet fully release-proven:

- normal first-turn context reduction should land in roughly the `25%` to `45%` range on mixed real workloads when packet shaping, memory, and retrieval all work together
- warm or repeated workflows should often exceed `90%` context reduction when prior retrieval work, compact packets, and memory reuse can replace raw replay
- external-tool workflows should see the biggest benefit because Bridge/MCP callers can reuse compact packets instead of re-sending transcripts and file excerpts each turn
- large-vault retrieval should remain in the sub-second operator-feels-fast range on healthy local indexes for common top-k style queries

These predictive numbers are inferred from the current synthetic, adversarial, and capped real-vault benchmark ranges already recorded in the repo. They should be treated as V1 targets until broader real-user-vault validation is complete.

## 2. Product Thesis

Users increasingly have valuable context spread across files, PDFs, notes, chat logs, screenshots, synced folders, and browser content, but their AI tools repeatedly lose that context or require expensive replay.

CML solves that by giving the user a local vault that can:

- ingest mixed artifacts
- index and cluster them
- extract durable memory and working memory
- serve compact evidence packets to internal chat and external tools
- keep a per-cluster expert lifecycle for deeper specialization

If CML works, the user stops treating every AI interaction as stateless and starts treating their personal context as reusable infrastructure.

## 3. Problem Statement

Current AI workflows break down in four ways:

1. Long-running chats lose important old context.
2. Users repeatedly pay token and attention cost to restate the same background.
3. External tools cannot safely reuse a private local corpus.
4. Retrieval-only systems often return loose snippets without a durable memory layer or inspectable packet structure.

CML must fix those failures without requiring the user to understand embeddings, vector databases, MCP internals, or LoRA training.

## 4. Target User

Primary user:

- an individual knowledge worker or student
- collects assignments, research, notes, exported chats, PDFs, screenshots, and links
- wants AI help grounded in their own corpus
- prefers local control and privacy over cloud-first collaboration

Secondary user:

- an AI power user who wants Claude, Codex, IDE agents, or local MCP clients to consume the same local context layer

V1 is not optimized for:

- teams
- enterprises with centralized admin
- browser-only users
- mobile-first workflows

## 5. Product Principles

1. Local-first by default.
2. Retrieval is the citation authority, not model memory.
3. Context must be inspectable, reversible, and source-grounded.
4. The desktop app is the control plane; the extension is only a capture surface.
5. User trust is more important than aggressive automation.
6. If public-quality gates fail, release slips.

## 6. V1 Product Definition

### 6.1 Platform

- Windows only
- downloadable desktop app
- no web-only fallback

### 6.2 Core Objects

- Vault: the local workspace and security boundary
- Source: a file, URL capture, pasted note, screenshot, transcript, or imported artifact
- Cluster: a user-visible grouping of related context
- Memory: distilled reusable facts, decisions, constraints, and working summaries
- Context packet: a compact, expandable delivery format for chat and Bridge
- Cluster expert: a per-cluster expert lifecycle with retrieval-backed use now and verified LoRA graduation as the public-quality target

### 6.3 Surfaces

Desktop navigation currently maps to:

- Mind/Home
- Sources
- Map
- Clusters
- Chat
- Bridge
- Settings
- Activity
- Timeline
- Tasks

External surfaces:

- local HTTP API
- MCP server
- CLI helper
- browser extension

## 7. User Jobs To Be Done

### 7.1 Build My Memory Layer

"Take my local material and make it searchable, clustered, and reusable without shipping it to the cloud."

### 7.2 Answer With My Context

"When I ask a question, use my vault and cite the evidence instead of relying on generic model memory."

### 7.3 Reuse Context Across Tools

"Let Claude, Codex, or another local AI tool request the right context packet from my vault instead of me manually pasting everything again."

### 7.4 Capture Context Quickly

"Save the page, screenshot, PDF link, selection, or file I am looking at into the right vault with minimal setup friction."

## 8. Scope For Public V1

### 8.1 In Scope

- explicit vault creation and selection
- local storage under a vault-owned data directory
- file, folder, text, URL, screenshot, image/OCR, PDF, DOCX, Markdown, TXT, JSON, CSV, and HTML ingestion paths where supported by the current pipeline
- watched local folders and local synced-folder imports
- semantic search plus exact fallback behavior
- clustering, cluster suggestions, merge flows, and cluster detail views
- retrieval-grounded chat with citations
- distilled memory, working memory, and bootstrap summaries
- compact context packets with expansion handles and packet telemetry
- Bridge/MCP/API/CLI access to local context
- browser extension setup and capture into the active vault
- hardware-aware model setup and local runtime management
- vault unlock, recovery, backup, and safety controls

### 8.2 Release-Gated In Scope

These are part of the V1 promise and cannot be silently deferred:

- compact reversible context delivery that is materially smaller than raw replay
- grounded chat quality under hostile or weak evidence
- dynamic evidence budgeting by hardware and model tier
- clean Windows packaging and clean-machine validation
- verified retrieval-grounded expert-compression bundle quality, not only scaffolding

### 8.3 Explicitly Out Of Scope

- mobile apps
- team collaboration
- cloud sync as a core V1 requirement
- full-device silent scanning
- SaaS multi-tenant hosting
- browser extension as an admin console

## 9. End-To-End User Flow

### 9.1 First Run

1. User launches the desktop app.
2. User creates or selects a vault.
3. User sets passphrase and recovery flow.
4. User imports files, folders, notes, or links.
5. User configures or downloads approved local models.
6. User waits for extraction, indexing, and clustering.
7. User lands in Mind with searchable context and visible cluster state.

### 9.2 Daily Use

1. User captures new material from desktop or extension.
2. Background jobs reconcile and index it.
3. CML updates source records, clusters, and memory layers.
4. User searches, opens a cluster, or starts a chat.
5. Chat retrieves evidence and optionally routes to expert assistance.
6. User inspects citations, saves useful answers, or exports context.

### 9.3 External Tool Use

1. User enables Bridge or configures a local client.
2. External tool requests a context packet for a question or cluster.
3. CML returns compact evidence, memory, citations, warnings, and expansion handles.
4. External tool may log its turn or save artifacts back into the vault.

## 10. Functional Requirements

### 10.1 Vault Management

The product must allow the user to:

- create, open, rename, and delete vaults
- choose a local vault path
- view vault readiness and storage status
- lock and unlock the vault
- use recovery and backup flows
- keep convenience mode and strict locked mode available as distinct behaviors

### 10.2 Source Ingestion

The product must:

- ingest sources from file path, pasted text, URL, extension capture, and local folder scan
- preserve source identity and metadata
- extract readable text or fall back safely when extraction fails
- support OCR for image-heavy documents where local OCR is available
- maintain page and chunk records for downstream retrieval
- expose processing state and failure state in the UI

### 10.3 Search And Retrieval

The product must:

- support semantic search across the vault
- support cluster-scoped retrieval
- support exact-search fallback and vector repair flows
- preserve citationability back to source records and pages
- expose scoring or diagnostics surfaces for deeper validation

### 10.4 Clusters

The product must:

- list clusters and show their source membership
- create and rename clusters
- suggest clusters automatically
- merge clusters
- show merge artifacts and rollback where supported
- surface cluster-level expert state

### 10.5 Chat

The product must:

- let the user start and revisit chat sessions
- support global and cluster-aware questioning
- store chat messages locally
- attach retrieval evidence and snapshots to answers
- expose compact/retention flows for long-running sessions
- stream or incrementally deliver context responses where supported

### 10.6 Memory Layer

The product must:

- extract distilled memory from grounded interactions and sources
- maintain working memory per vault and cluster
- generate bootstrap summaries for new vaults or clusters
- preserve provenance so memory items can be inspected and justified

### 10.7 Context Packets

The product must:

- build model-ready context packets rather than raw diagnostic JSON by default
- combine retrieved evidence with memory and operating instructions
- provide expansion handles for deeper evidence access
- track packet savings telemetry against raw replay baselines
- serve the same packet model to both internal chat and external Bridge clients

### 10.8 Bridge And External Access

The product must:

- expose local API endpoints for Bridge status, clients, requests, captures, reviews, and context
- expose an MCP-compatible server path
- provide CLI access for terminal workflows
- support scoped client permissions
- log recent external access activity
- keep writeback review and trust gating visible

### 10.9 Browser Extension

The extension must remain intentionally thin:

- import desktop-issued setup JSON
- validate connection to the local backend
- save link/page-style captures into the vault
- save screenshots and uploads through the local extension endpoints

Manual setup friction should be minimized in favor of desktop-provisioned setup.

### 10.10 Model And Runtime Setup

The product must:

- detect hardware capability
- recommend approved chat and embedding configurations
- distinguish chat runtime requirements from expert runtime requirements
- reject incompatible imported models with explicit reasons
- avoid pretending full local chat works when no synthesis runtime is configured

### 10.11 Cluster Experts

The product must maintain a per-cluster expert lifecycle with:

- dataset/export readiness
- job state
- runtime validation
- artifact activation
- rollback
- status reporting in UI and API

Important product rule:

- public-facing "trained expert" claims require verified graduation and quality proof
- retrieval-backed operation before that is allowed, but it is not the final marketing claim

## 11. UX Requirements

### 11.1 Information Architecture

The desktop app should behave like a calm local workspace, not an ML dashboard.

Required UX behaviors:

- land on Mind/Home after onboarding
- make chat easy to reach, but not the only first surface
- keep sources, clusters, map, and Bridge legible to non-technical users
- expose advanced details progressively

### 11.2 Trust And Transparency

The UI must make clear:

- what cluster or retrieval scope was used
- what evidence supports the answer
- whether the system is degraded, locked, or still learning
- whether Bridge is enabled and which client accessed context
- whether a remote or local runtime is being used

### 11.3 Status Language

User-facing labels should prefer understandable terms such as:

- Searchable now
- Learning
- Ready
- Needs update
- Issue

Internal implementation states can stay richer in the backend.

## 12. Technical Architecture

Current architecture is:

- desktop shell: Electron
- frontend: React + TypeScript + TanStack Router
- backend: FastAPI
- metadata and authoritative store: SQLite
- retrieval: local embeddings with exact and vector-based paths
- OCR and document parsing: local Python pipeline
- extension: Chromium Manifest V3 package

Product documentation must treat this as the actual V1 stack, not an open Tauri-versus-Electron decision.

## 13. Security And Privacy Requirements

The product must:

- keep user data local by default
- fail closed on vault lock and setup boundaries
- keep raw file access and external access explicitly scoped
- avoid treating Bridge as a magical anti-exfiltration barrier
- require explicit trust and review for unsafe writeback or weakly grounded external responses
- keep encryption, unlock enforcement, parser/browser isolation, and renderer hardening as release concerns, not polish

## 14. Success Metrics

### 14.1 Product Metrics

- time to first indexed answer
- successful import rate across supported source types
- percentage of chats with usable citations
- context packet savings versus raw replay
- Bridge request success rate
- extension capture success rate
- cluster suggestion acceptance or correction rate

### 14.1.1 Impact Targets

- average first-turn context reduction target: `>=25%` on representative mixed-vault tasks
- strong-workflow first-turn target: `~35% to 45%` when retrieval and packet shaping have high-quality evidence
- warm-cache / repeated-workflow reduction target: `>=90%`
- Bridge packet savings target: measurable positive savings on default packet mode, with broader goals in the `20%+` average range on mixed external-context tasks
- real-vault query responsiveness target: commonly sub-second p95 for capped user-scale retrieval benchmarks after indexing is healthy

### 14.2 Release Metrics

- clean-machine install success
- first-run readiness success
- large-vault ingestion and query latency targets
- hostile-evidence downgrade accuracy
- verified expert quality delta over retrieval-only baseline

## 15. Risks

1. Verified LoRA quality may lag far behind the broader product.
2. Packaging a Python-heavy desktop product with OCR and local runtimes is operationally expensive.
3. Search, chat, and memory quality can drift if product claims outrun current evidence.
4. UI trust can be damaged by hardcoded or misleading health states.
5. External access increases privacy expectations and review burden.

## 16. Mitigations

- keep `PROJECT_CONTEXT` as the release-truth document
- separate "implemented surface" from "release-cleared claim"
- keep retrieval as the citation authority
- use bounded pagination, caching, and repair flows for scale
- make Bridge permissions, review, and logging explicit
- validate on real and synthetic vaults, not only unit tests

## 17. Release Gates

Public V1 cannot ship unless these are green:

- clean Windows VM installation and first-run validation
- stable vault creation, unlock, ingestion, search, and chat
- compact context packet delivery with measurable savings
- grounded-response behavior under low-trust or hostile evidence
- extension capture setup from the desktop flow
- hardware-aware model setup that avoids unusable recommendations
- verified expert proof that is honest about its quality level

## 18. Non-Goals For Resume Framing

When this document is used to derive resume bullets, do not flatten the project into "built a note-taking app" or "made a vector search tool." The differentiated scope is:

- local-first AI context operating layer
- desktop plus backend plus extension architecture
- retrieval, memory, clustering, and context-packet delivery
- external AI tool integration through Bridge, API, CLI, and MCP
- security, packaging, and release-hardening work

## 19. Resume Extraction Notes

The strongest resume themes supported by the codebase are:

- architected a Windows desktop AI product spanning Electron, React, FastAPI, SQLite, and browser-extension capture
- built local document ingestion pipelines for PDFs, OCR, URLs, notes, and synced folders with chunking, indexing, and retrieval
- implemented grounded chat, memory extraction, context compression, and external-tool context delivery via HTTP API and MCP
- designed secure local-vault workflows including lock state, recovery, scoped Bridge permissions, auditability, and startup validation
- shipped benchmark, packaging, smoke-test, and release-readiness infrastructure for a Python-backed desktop application

## 20. Open Questions

- what minimum hardware tier can honestly support verified expert mode
- what approved chat/expert pairing matrix will be published for V1
- whether extension UX needs a cursor-local capture palette before release
- what exact external clients will be officially documented first
- what public language will be used if retrieval quality is release-ready before verified expert quality is
