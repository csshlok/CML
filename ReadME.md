<p align="center">
  <img src="apps/desktop/public/brand/vault-logo.png" width="148" alt="CML logo">
</p>

<h1 align="center">CML</h1>

<p align="center">
  <em>A local-first context management layer for files, chats, retrieval, and cluster experts.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows%20V1-111111?style=flat-square" alt="Windows V1">
  <img src="https://img.shields.io/badge/runtime-Electron%20%2B%20FastAPI-111111?style=flat-square" alt="Electron and FastAPI">
  <img src="https://img.shields.io/badge/storage-local--first-111111?style=flat-square" alt="Local first">
  <img src="https://img.shields.io/badge/status-pre--release-111111?style=flat-square" alt="Pre-release">
</p>

<p align="center">
  <strong>Compact context packets · retrieval-first chat · local vaults · verified cluster-expert path</strong>
</p>

---

CML is a downloadable desktop app that turns a user's local vault of files, notes, links, screenshots, PDFs, transcripts, and imported folders into:

- inspectable source memory
- semantic retrieval and clustering
- distilled memory and working memory
- compact reversible context packets for chat and Bridge/MCP
- a per-cluster local expert lifecycle

This is not just a searchable vault. Public V1 is aiming at a real context-management layer between the user and an LLM: preserve long-lived context outside the model, reduce repeated transcript/file replay, and let external tools request compressed grounded context instead of re-reading raw history.

## Why CML

Most AI workspaces stop at “upload files and retrieve top-k chunks.”

CML is trying to solve a broader problem:

- long chats lose context
- old decisions disappear
- raw transcripts are expensive to replay
- external tools cannot reuse your local memory cleanly
- grounded answers need more than prompt wording

CML’s current architecture addresses that with:

- retrieval-first routing
- grounded chat with citations
- distilled memory and working-memory summaries
- compact context packets with expansion handles
- trust gating for hostile or weak evidence
- Bridge/MCP flows for external capture and context reuse

## What Exists Today

Current repo state already includes:

- Electron desktop shell in `apps/desktop`
- FastAPI backend in `backend`
- local vault creation and storage under `.vault`
- source ingestion for text, Markdown, DOCX, PDF, links, images/OCR, pasted text, and tracked folders
- semantic search, chunking, clustering, and move suggestions
- retrieval-grounded chat with citations, recent-turn handling, degraded fallback states, and dynamic context budgeting
- distilled memory, working memory, bootstrap summaries, and memory-backed context packets
- Bridge/MCP packet formatting, capture receipts, writeback review flows, expansion handles, and extension capture plumbing
- browser extension package with page, selection, PDF URL, file-upload, and screenshot capture paths
- turbovec sidecar integration with exact fallback, repair flows, and Phase C approval gating
- packaging scripts, packaged smokes, security audits, and broader backend regression coverage

The live source of truth for project status is [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md).

## Current Release Gates

CML is not public-release cleared yet.

The biggest remaining gates are:

- clean Windows VM validation of the current package
- installed-app first-run parity on a healthy clean VM
- real LoRA trainer/runtime proof on release-like hardware
- live adapter quality benchmark versus retrieval baseline
- hardware-aware model/setup QA
- broader real-vault and context-layer release proof

That release posture is intentional. If the public-quality bar is not met, release slips rather than turning into a private demo.

## Quick Navigation

- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Repo Map](#repo-map)
- [Bridge And External Use](#bridge-and-external-use)
- [Local Expert Path](#local-expert-path)
- [Packaging And Validation](#packaging-and-validation)
- [Development Workflow](#development-workflow)
- [Important Docs](#important-docs)

## Quick Start

### Prerequisites

- Node.js 18+
- Python 3.11+ recommended
- Windows is the public V1 target

Create a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

Install dependencies:

```bash
npm install
pip install -r requirements/contributors-backend.txt
```

The backend reads settings from `.env`. Start from `.env.example`.

### Run the backend

```bash
npm run backend
```

If you want a fixed dev token for manual API calls:

```powershell
$env:CML_API_TOKEN="dev-token"
npm run backend
```

### Run the desktop app

```bash
npm run dev
```

### Useful checks

```bash
curl http://127.0.0.1:7343/health
curl -H "x-cml-api-token: dev-token" http://127.0.0.1:7343/api/v1/system/backend-identity
curl -H "x-cml-api-token: dev-token" http://127.0.0.1:7343/api/v1/bridge/status
```

Dev web UI:

```text
http://127.0.0.1:5173/
```

## Architecture

CML is currently built as:

- desktop shell: Electron
- UI: React + TanStack
- backend: FastAPI
- metadata/state: SQLite
- retrieval: local embeddings plus exact/turbovec vector backends
- OCR: local Tesseract/OCRmyPDF/PyMuPDF path
- external access: Bridge HTTP API, MCP server, CLI helpers, browser extension

Core runtime rule:

- SQLite is authoritative
- vector indexes are derived state
- Bridge is scoped access, not a magic anti-exfiltration wall
- citations come from retrieval, not model memory

## Repo Map

- `apps/desktop/` — Electron shell and React desktop UI
- `apps/browser-extension/` — packaged browser extension capture client
- `backend/` — FastAPI service, retrieval, Bridge, ingestion, expert lifecycle, startup repair, security boundaries
- `docs/` — PRDs, architecture, current context, release checklists, benchmark notes, design docs
- `scripts/` — backend smokes, packaging scripts, OCR/model tooling, security checks, benchmark runners
- `requirements/` — contributor dependency manifests
- `UI-ref/` — preserved UI reference material

## Bridge And External Use

CML exposes local context to outside tools through:

- MCP server
- local HTTP API
- CLI helpers
- browser extension capture flows

Current Bridge capabilities include:

- list clusters
- request grounded context packets
- expand packet handles
- log external turns
- capture artifacts
- inspect downgraded writeback reviews
- approve or keep gated external writebacks

Current dev helpers:

```powershell
$env:CML_BRIDGE_TOKEN="token-from-bridge-settings"
.\scripts\bridge\cml-bridge.ps1 "retrieve context for my assignment"
.\.venv\Scripts\python.exe -m backend.app.bridge_mcp
```

## Local Expert Path

Public V1 requires a real per-cluster expert path, but current claims stay conservative until real proof exists.

Current expert state surface includes:

- dataset export and dataset-quality gates
- trainer process handoff
- adapter artifact validation
- activation and rollback
- runtime-load contract metadata
- Expert tab/state visibility
- deterministic scaffold smokes

Current expert states:

- `retrieval_ready`
- `training_pending`
- `training_running`
- `training_ready`
- `training_failed`
- `hardware_unsupported`
- `rollback_ready`

Important rule:

- do not call a cluster expert “trained” in release language until a real adapter has passed graduation, runtime loading, and quality proof

Useful commands:

```powershell
curl http://127.0.0.1:7343/api/v1/system/lora-trainer
.\scripts\backend\smoke-lora-expert.ps1
.\scripts\backend\smoke-lora-runtime.ps1 -AdapterPath <adapter-dir> -BaseModel <base-model> -RuntimeUrl http://127.0.0.1:8080/v1
```

## Packaging And Validation

Windows packaging is driven through:

```bash
npm run package:win
```

That delegates to:

```text
scripts/packaging/package-windows.ps1
```

Current validation coverage includes:

- clean-machine structure validation
- packaged runtime smoke
- packaged full-vault smoke
- packaged dynamic-link smoke
- packaged migration drill
- packaged app-launch smoke
- installed-app smoke

The main packaging blocker is no longer the older missing-resource state. It is trustworthy clean-VM validation of the current package.

## Development Workflow

Build the desktop app:

```bash
npm run build
```

Electron behavior tests:

```bash
npm run lint
```

Backend syntax check:

```powershell
.\.venv\Scripts\python -m compileall backend\app
```

Renderer security audit:

```bash
npm run security:renderer
```

Package layout and helper manifest audit:

```bash
npm run security:package
```

At the end of meaningful work, keep [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) current.

## Important Docs

### Product And Current State

- [docs/PROJECT_CONTEXT.md](docs/PROJECT_CONTEXT.md) — compact live project status
- [docs/OVERALL_CONTEXT.md](docs/OVERALL_CONTEXT.md) — long-form fallback context
- [docs/PRODUCT_PRD.md](docs/PRODUCT_PRD.md) — product requirements
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — high-level architecture

### UI

- [docs/UI_PRD.md](docs/UI_PRD.md) — UI requirements
- [docs/UI_ARCHITECTURE.md](docs/UI_ARCHITECTURE.md) — concrete desktop UI architecture
- [docs/ONBOARDING_PRD.md](docs/ONBOARDING_PRD.md) — first-run setup flow

### Context Layer And Retrieval

- [docs/CONTEXT_LAYER_V1_WORKPATH.md](docs/CONTEXT_LAYER_V1_WORKPATH.md) — context-layer implementation track
- [docs/BRIDGE_CONTEXT_PACKET_DESIGN.md](docs/BRIDGE_CONTEXT_PACKET_DESIGN.md) — Bridge packet design and current implementation status
- [docs/DYNAMIC_CONTEXT_BUDGETING_DESIGN.md](docs/DYNAMIC_CONTEXT_BUDGETING_DESIGN.md) — dynamic evidence budget design and current implementation status
- [docs/TURBOVEC_INTEGRATION_PLAN.md](docs/TURBOVEC_INTEGRATION_PLAN.md) — turbovec rollout status and remaining evidence work
- [docs/RETRIEVAL_BENCHMARKS.md](docs/RETRIEVAL_BENCHMARKS.md) — retrieval benchmark evidence

### Release And Validation

- [docs/V1_RELEASE_CHECKLIST.md](docs/V1_RELEASE_CHECKLIST.md) — live release-gate summary
- [docs/WINDOWS_VM_VALIDATION.md](docs/WINDOWS_VM_VALIDATION.md) — clean-VM validation state
- [docs/PACKAGING_INVESTIGATION.md](docs/PACKAGING_INVESTIGATION.md) — packaging state and remaining blocker
- [docs/EXPERT_VALIDATION_REPORT.md](docs/EXPERT_VALIDATION_REPORT.md) — real LoRA proof status
- [docs/RELEASE_AUDIT.md](docs/RELEASE_AUDIT.md) — release-readiness audit

## Notes

- Public V1 target is Windows-only.
- Local-first and offline-first where practical.
- No silent full-device scan in V1.
- Model weights are not bundled in the first installer.
- Hash embeddings are development-only, not the intended production setup path.

## License

This repository does not currently expose a root license file in the workspace snapshot I updated against. If you want public-distribution README polish to look complete, the next obvious repo hygiene step is to add an explicit top-level license file and reference it here.
