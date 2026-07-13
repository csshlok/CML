<p align="center">
  <img src="apps/desktop/public/brand/logo-readme.svg" width="420" alt="CML logo">
</p>

<h1 align="center">CML</h1>

<p align="center">
  <em>A private Windows workspace that turns local files and code projects into searchable, reusable AI context.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows%20V1-111111?style=flat-square" alt="Windows V1">
  <img src="https://img.shields.io/badge/runtime-Electron%20%2B%20FastAPI-111111?style=flat-square" alt="Electron and FastAPI">
  <img src="https://img.shields.io/badge/architecture-RAG--only-111111?style=flat-square" alt="RAG only">
  <img src="https://img.shields.io/badge/status-pre--release-111111?style=flat-square" alt="Pre-release">
</p>

---

## What CML Is

CML powers the Vault desktop app. Vault turns local files, notes, links, screenshots, PDFs, transcripts, synced folders, and code projects into searchable context for local AI.

Use Vault to:

- keep useful context across conversations
- find answers grounded in your own sources, with citations
- organize related material into clusters
- ask questions about an indexed code project with Odin
- share only approved local context with Bridge, MCP clients, and command-line tools

The live architecture is now RAG-only. The old LoRA cluster-expert path has been removed from the product code.

## Quick Navigation

- [What CML Is](#what-cml-is)
- [What You Can Do](#what-you-can-do)
- [Architecture At A Glance](#architecture-at-a-glance)
- [Using Vault](#using-vault)
- [Quick Start](#quick-start)
- [Contributor Checks](#contributor-checks)
- [Bridge And External Tooling](#bridge-and-external-tooling)
- [Token Reduction](#token-reduction)
- [Packaging](#packaging)
- [Important Docs](#important-docs)

## What You Can Do

The current app supports:

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

## How The Design Helps

Most AI workflows break down in the same places:

- context gets lost across long chats
- users keep replaying the same documents
- external tools cannot safely reuse local context
- "retrieval" often stops at loose snippets with weak structure

Vault addresses those problems with a local system that is inspectable and reversible:

- grounded retrieval
- working memory and distilled memory
- reusable context packets
- explicit trust boundaries
- shared internal and external context surfaces

## Using Vault

1. Create a library and choose where it should live on your device.
2. Set up Memory Search so Vault can find related passages locally.
3. Add files, folders, links, notes, screenshots, or transcripts from Sources.
4. Review indexing progress in Tasks or Settings → Health.
5. Ask a question from Home or Chat. Open a citation to inspect the supporting source.
6. Use Clusters, Map, and Timeline to explore related material.

For a code project, open PowerShell in the project folder and run:

```powershell
.\odin.ps1 project add . --name "My Project"
```

Odin creates a searchable project index without modifying repository files. Use `project sync`, `project show`, `project graph`, or `project tree` when the project changes or when you need a structural view.

## Quick Start

Vault is currently pre-release, so the repository is the supported installation path.

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

Settings commonly used for local development:

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

## Contributor Checks

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

Vault exposes approved local context to external tools through:

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

## Release Status

Vault is currently pre-release.

The migration to RAG is complete, but release hardening still remains:

- clean-machine package validation
- broader release proof
- normal local synthesis runtime setup on target machines

The installer will not be presented as release-ready until those checks pass.

## Notes

- Public V1 target is Windows-only.
- The first installer does not bundle model weights.
- Vault does not silently scan the entire device.
- Hash embeddings are for development and benchmark fallback, not the intended production setup path.

## License

No top-level license has been selected yet. Treat the source as all-rights-reserved until a license file is added.
