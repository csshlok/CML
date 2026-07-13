<p align="center">
  <img src="apps/desktop/public/brand/Frame%208.png" width="360" alt="Vault logo">
</p>

<h1 align="center">Vault</h1>

<h2 align="center">a context management layer</h2>

<p align="center">
  Vault turns the files, notes, links, and code you already work with into private, searchable context for AI.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-1f2937.svg" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/platform-Windows-1f2937.svg" alt="Windows">
  <img src="https://img.shields.io/badge/status-pre--release-1f2937.svg" alt="Pre-release">
</p>

Vault is a local-first desktop workspace for building reliable context around your work. It indexes approved sources, retrieves the most relevant evidence, and gives you grounded answers with citations. Your files stay on your machine unless you explicitly connect an external model or tool.

## What Vault does

- **Capture** files, folders, Markdown, DOCX, PDFs, URLs, images, OCR text, notes, and browser content.
- **Organize** related material into clusters that give each topic or project a durable home.
- **Search** across your sources with retrieval that keeps evidence and citations attached to each answer.
- **Ask** questions in Chat or Home and inspect the sources behind the response.
- **Understand codebases** with Odin, Vault's project indexing layer for structure, symbols, dependencies, and project summaries.
- **Share selectively** through the Bridge API, MCP, and command-line helpers when another tool needs approved context.

## Odin project indexing

Odin indexes a codebase without changing repository files. Run it from PowerShell in the project directory:

```powershell
.\odin.ps1 project add . --name "My Project"
```

Useful commands:

```powershell
.\odin.ps1 project list
.\odin.ps1 project show <project-id>
.\odin.ps1 project sync <project-id>
.\odin.ps1 project graph <project-id>
.\odin.ps1 project tree <project-id>
.\odin.ps1 project remove <project-id>
```

The graph and tree are available when you need a structural view; the normal Vault experience stays focused on a short project brief and an AI workspace for questions.

## Architecture

Vault has two local processes:

- **Desktop app** — Electron and React UI in [`apps/desktop`](apps/desktop)
- **Backend** — FastAPI service for ingestion, storage, retrieval, clustering, memory, Bridge, and Odin in [`backend`](backend)

SQLite is the source of truth. Embeddings and vector indexes are derived state. Answers are synthesized from retrieved context packets rather than hidden application memory.

## Requirements

- Windows 10 or later (the current V1 target)
- Node.js 18 or later
- Python 3.11 or later

## Development setup

Clone the repository, create a virtual environment, and install the development dependencies:

```powershell
git clone https://github.com/csshlok/CML.git
cd graphify
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements/contributors-backend.txt
npm install
```

Copy `.env.example` to `.env` and adjust settings only when needed. Then start the backend and desktop app in separate terminals:

```powershell
npm run backend
npm run dev
```

The backend listens on `http://127.0.0.1:7343` and the development UI on `http://127.0.0.1:5173`.

## Checks

```powershell
npm run lint
npm run build
.\.venv\Scripts\python.exe -m pytest -q backend/tests
.\.venv\Scripts\python.exe -m compileall -q backend\app scripts\backend backend\tests
```

## Repository guide

- [`apps/desktop`](apps/desktop) — Electron shell and desktop UI
- [`apps/browser-extension`](apps/browser-extension) — browser capture client
- [`backend`](backend) — API, ingestion, retrieval, clustering, memory, Bridge, and Odin
- [`docs`](docs) — product, architecture, UI, and implementation documentation
- [`scripts`](scripts) — development, smoke-test, benchmark, and packaging helpers

Start with [`docs/PROJECT_CONTEXT.md`](docs/PROJECT_CONTEXT.md) for the current product context and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the system design.

## Privacy and data boundaries

Vault does not silently scan your device. Sources are added explicitly, stored within the selected vault, and available for review or removal. External context access is opt-in and exposed through authenticated Bridge and MCP surfaces.

## Project status

Vault is pre-release software. The core local workflow is under active development, and Windows packaging and clean-machine validation are still being hardened. Do not use it as the only copy of important data.

## License

Vault is available under the [MIT License](LICENSE).
