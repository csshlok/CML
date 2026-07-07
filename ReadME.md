<p align="center">
  <img src="apps/desktop/public/brand/logo-readme.svg" width="420" alt="CML logo">
</p>

<h1 align="center">CML</h1>

<p align="center">
  <em>We are building a local-first context management layer for grounded chat, retrieval, and reusable AI context packets.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows%20V1-111111?style=flat-square" alt="Windows V1">
  <img src="https://img.shields.io/badge/runtime-Electron%20%2B%20FastAPI-111111?style=flat-square" alt="Electron and FastAPI">
  <img src="https://img.shields.io/badge/architecture-RAG--only-111111?style=flat-square" alt="RAG only">
  <img src="https://img.shields.io/badge/status-pre--release-111111?style=flat-square" alt="Pre-release">
</p>

---

## What CML Is

CML turns a local vault of files, notes, links, screenshots, PDFs, transcripts, and synced folders into reusable AI context.

We are not trying to build "just another file uploader for chat." The point of CML is to:

- keep long-lived context outside the model
- retrieve grounded evidence with citations
- distill working memory and reusable memory from the vault
- return compact context packets instead of replaying raw history every turn
- let the desktop app, Bridge, MCP clients, and local tools all consume the same context layer

The live architecture is now RAG-only. The old LoRA cluster-expert path has been removed from the product code.

## Quick Navigation

- [What CML Is](#what-cml-is)
- [Current State](#current-state)
- [Architecture At A Glance](#architecture-at-a-glance)
- [Quick Start](#quick-start)
- [Developer Workflow](#developer-workflow)
- [Bridge And External Tooling](#bridge-and-external-tooling)
- [Token Reduction](#token-reduction)
- [Packaging](#packaging)
- [Important Docs](#important-docs)

## Current State

What is live in the repo right now:

- Electron desktop app in `apps/desktop`
- FastAPI backend in `backend`
- local vault creation and vault-scoped storage
- ingestion for text, Markdown, DOCX, PDF, URLs, images, OCR, pasted text, and folder-based sources
- chunking, embeddings, retrieval, clustering, and cluster profile refresh
- grounded chat with citations and retrieval-first fallback behavior
- Bridge HTTP API and MCP integration
- browser extension capture flows
- packet shaping, working memory, memory items, and retrieval-driven token reduction
- packaging, smoke scripts, and backend regression coverage

Project status is tracked in:

- [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md)
- [docs/OVERALL_CONTEXT.md](docs/OVERALL_CONTEXT.md)
- [docs/LORA_TO_RAG_MIGRATION_PLAN.md](docs/LORA_TO_RAG_MIGRATION_PLAN.md)

## Architecture At A Glance

The current contract is straightforward:

- retrieval is the authority for facts, citations, source IDs, names, numbers, and dates
- clusters are retrieval scopes with cached metadata like summaries and glossaries
- chat and Bridge both consume retrieval-first context packets
- token reduction comes from packet shaping, citation selection, memory reuse, and caching

Core rule:

- SQLite is authoritative
- vector indexes are derived state
- retrieval owns evidence
- models synthesize from packets, not from hidden app memory

## Why We Built It This Way

Most AI workflows break down in the same places:

- context gets lost across long chats
- users keep replaying the same documents
- external tools cannot safely reuse local context
- "retrieval" often stops at loose snippets with weak structure

We are trying to solve those problems with a local system that is inspectable and reversible:

- grounded retrieval
- working memory and distilled memory
- reusable context packets
- explicit trust boundaries
- shared internal and external context surfaces

## Quick Start

### Prerequisites

- Node.js 18+
- Python 3.11+
- Windows is the primary target environment

### 1. Install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements/contributors-backend.txt
npm install
```

### 2. Start from the example env file

Copy `.env.example` to `.env` and adjust only what you actually need. The backend already has sensible local defaults for normal development.

Important settings you will usually care about:

- `CML_API_PREFIX`
- `CML_DATABASE_PATH`
- `CML_DATA_DIR`
- `CML_MODELS_DIR`
- `CML_API_TOKEN`
- `CML_EMBEDDING_PROVIDER`

### 3. Run the backend

```bash
npm run backend
```

If you want authenticated manual API calls in local development:

```powershell
$env:CML_API_TOKEN = "dev-token"
npm run backend
```

Default local backend URL:

```text
http://127.0.0.1:7343
```

### 4. Run the desktop app

```bash
npm run dev
```

Default dev UI:

```text
http://127.0.0.1:5173/
```

## Useful Local Checks

Backend health:

```bash
curl http://127.0.0.1:7343/health
```

Backend identity:

```bash
curl -H "x-cml-api-token: dev-token" http://127.0.0.1:7343/api/v1/system/backend-identity
```

Bridge status:

```bash
curl -H "x-cml-api-token: dev-token" http://127.0.0.1:7343/api/v1/bridge/status
```

Vault list:

```bash
curl -H "x-cml-api-token: dev-token" http://127.0.0.1:7343/api/v1/vaults
```

## Developer Workflow

### Desktop build

```bash
npm run build
```

### Desktop behavior tests

```bash
npm run lint
```

### Backend regression tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend/tests
```

### Backend compile check

```powershell
.\.venv\Scripts\python.exe -m compileall -q backend\app scripts\backend backend\tests
```

### Renderer and package security checks

```bash
npm run security:renderer
npm run security:package
```

### TypeScript check

```bash
npx tsc --project apps/desktop/tsconfig.json --noEmit
```

## Repo Map

- `apps/desktop/` - Electron shell and React/TanStack desktop UI
- `apps/browser-extension/` - browser capture client
- `backend/` - FastAPI API, retrieval, Bridge, ingestion, clustering, memory, and security boundaries
- `docs/` - current context, architecture, PRDs, implementation notes, and migration record
- `scripts/` - packaging, smoke tests, benchmarks, and operational helpers
- `requirements/` - contributor Python dependency manifests
- `UI-ref/` - preserved visual reference material

## Bridge And External Tooling

We expose local context to external tools through:

- Bridge HTTP API
- MCP server
- CLI helpers
- browser extension capture paths

Current Bridge capabilities include:

- list clusters
- request grounded context packets
- expand packet handles
- capture external artifacts
- log external turns
- review downgraded writebacks

Useful dev entry points:

```powershell
$env:CML_BRIDGE_TOKEN = "<bridge-token>"
.\scripts\bridge\cml-bridge.ps1 "retrieve context for my assignment"
.\.venv\Scripts\python.exe -m backend.app.bridge_mcp
```

## Token Reduction

The token-reduction story is now retrieval-driven, not model-compression-driven.

Current benchmark evidence in the repo shows:

- average raw tokens: `1858.62`
- average current packet tokens: `1030.38`
- average reduction: `44.43%`
- warm-cache average reduction: `94.8%`

That reduction currently comes from:

- relevance filtering
- citation trimming and dedupe
- working-memory reuse
- cached cluster profile material
- repeat-query cache behavior

## Packaging

Windows packaging entry point:

```bash
npm run package:win
```

Main packaging script:

```text
scripts/packaging/package-windows.ps1
```

Current packaging validation in the repo includes:

- packaged runtime smoke
- package layout checks
- helper manifest validation
- app launch smoke
- migration drill smoke
- full-vault smoke

## Important Docs

Current-truth docs:

- [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md)
- [docs/OVERALL_CONTEXT.md](docs/OVERALL_CONTEXT.md)
- [docs/LORA_TO_RAG_MIGRATION_PLAN.md](docs/LORA_TO_RAG_MIGRATION_PLAN.md)

Core product and architecture docs:

- [docs/PRODUCT_PRD.md](docs/PRODUCT_PRD.md)
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/UI_PRD.md](docs/UI_PRD.md)
- [docs/UI_ARCHITECTURE.md](docs/UI_ARCHITECTURE.md)
- [docs/ONBOARDING_PRD.md](docs/ONBOARDING_PRD.md)

Retrieval and packet docs:

- [docs/BRIDGE_CONTEXT_PACKET_DESIGN.md](docs/BRIDGE_CONTEXT_PACKET_DESIGN.md)
- [docs/CONTEXT_LAYER_V1_WORKPATH.md](docs/CONTEXT_LAYER_V1_WORKPATH.md)
- [docs/DYNAMIC_CONTEXT_BUDGETING_DESIGN.md](docs/DYNAMIC_CONTEXT_BUDGETING_DESIGN.md)
- [docs/RETRIEVAL_BENCHMARKS.md](docs/RETRIEVAL_BENCHMARKS.md)
- [docs/TURBOVEC_INTEGRATION_PLAN.md](docs/TURBOVEC_INTEGRATION_PLAN.md)

## Release Posture

We are still pre-release.

The migration to RAG is complete, but release hardening still remains:

- clean-machine package validation
- broader release proof
- continued docs cleanup for older LoRA-era wording
- normal local synthesis runtime setup on target machines

We keep the bar conservative on purpose. If the release-quality bar is not met, we slip the release instead of pretending the repo is ready.

## Notes

- Public V1 target is Windows-only.
- We do not bundle model weights in the first installer.
- We do not do silent full-device scanning in V1.
- Hash embeddings are for development and benchmark fallback, not the intended production setup path.

## License

This repository still needs an explicit top-level license file if you want the public repo surface to look complete.
