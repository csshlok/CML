<p align="center">
  <img src="apps/desktop/public/brand/Frame%208.png" width="420" alt="Vault logo">
</p>

<h1 align="center">Vault</h1>

<h3 align="center">a context management layer</h3>

<p align="center">
  Turn your files, notes, links, and codebases into private, reusable context for AI.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-1f2937.svg" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/platform-Windows-1f2937.svg" alt="Windows">
  <img src="https://img.shields.io/badge/status-pre--release-b7791f.svg" alt="Pre-release">
  <img src="https://img.shields.io/badge/storage-local--first-2f855a.svg" alt="Local-first storage">
</p>

Vault gives AI a durable memory outside the chat window. Add the material you already work with, ask questions in plain language, and get answers grounded in your own sources—with citations you can inspect.

It is a local-first Windows desktop app, a retrieval system, and a controlled bridge between your private context and the AI tools you choose to use.

> [!IMPORTANT]
> Vault is pre-release software. The repository is currently the supported way to run it; a public installer is not ready yet.

## Why Vault exists

AI conversations are temporary. Your work is not.

Important decisions end up scattered across documents, meeting notes, browser tabs, screenshots, repositories, and old chats. Passing all of that back to a model on every request is slow, expensive, and unreliable. It also makes it difficult to tell where an answer came from.

Vault keeps that context outside the model and retrieves only what a question needs.

| Without Vault | With Vault |
| --- | --- |
| Re-upload the same files in every conversation | Add a source once and reuse it across sessions |
| Paste large folders or transcripts into prompts | Retrieve a focused context packet for each question |
| Trust answers without knowing their origin | Open the citations behind an answer |
| Keep every project in a separate AI silo | Reuse approved context across projects and tools |
| Manually explain an unfamiliar repository | Ask Odin about its structure, symbols, and dependencies |

## What you can do

- **Build a private knowledge base** from files, folders, notes, links, screenshots, PDFs, and transcripts.
- **Ask grounded questions** and inspect the source passages used to answer them.
- **Group related work into clusters** for projects, clients, research topics, or areas of responsibility.
- **Search across your context** without remembering where a detail was originally stored.
- **Index codebases with Odin** and ask how a project works without browsing every file manually.
- **Request graphs and trees when needed** while keeping the normal interface focused on useful summaries and answers.
- **Connect external tools deliberately** through Bridge, MCP, and the local API.
- **Keep control of your data** with explicit vault locations, local storage, and reviewable access boundaries.

## A typical workflow

1. Create a vault in a folder you control.
2. Add files, folders, links, notes, screenshots, or a code project.
3. Vault extracts the content, creates searchable chunks, and builds a local index.
4. Organize related sources into clusters or let Vault suggest useful groupings.
5. Ask a question from Home or Chat.
6. Vault retrieves the strongest supporting evidence and builds a bounded context packet.
7. The answer includes citations so you can inspect the original material.

```text
Your sources
    ↓
Extraction and indexing
    ↓
Local vault + searchable index
    ↓
Relevant evidence + memory + cluster profile
    ↓
Bounded context packet
    ↓
Vault chat, Bridge, MCP, or an approved external tool
```

## Supported sources

Vault currently supports:

- plain text and Markdown
- PDF and DOCX documents
- web pages and saved links
- images and screenshots through OCR
- pasted notes and transcripts
- folders and synced-folder sources
- source code and complete repositories through Odin
- browser captures through the companion extension

Every source remains reviewable and removable. Vault does not silently scan your device.

## Odin: understand a codebase without reading all of it

Odin is Vault's project-context layer. It registers a repository as a first-class project, indexes its files, extracts deterministic structure, connects it to retrieval, and exposes the result to Vault and approved outside tools.

From PowerShell in a source checkout:

```powershell
.\odin.ps1 project add . --name "My Project" --scope context
```

The default `context` scope includes source code plus useful repository documentation and configuration. Use `--scope code` when you want a source-focused index, or change the persisted choice during a later sync:

```powershell
.\odin.ps1 project add . --name "My Project" --scope code
.\odin.ps1 project sync . --scope context
```

Then ask questions or inspect the project:

```powershell
# See registered projects and indexing state
.\odin.ps1 project list
.\odin.ps1 project status .

# Update or rebuild the index
.\odin.ps1 project sync .
.\odin.ps1 project reindex . --layer retrieval

# Ask about the project
.\odin.ps1 context "How does authentication work?" --project .
.\odin.ps1 project explain . register_project
.\odin.ps1 project path . register_project build_structure_graph

# Request structural output
.\odin.ps1 project graph . --query "project indexing" --depth 2 --format markdown
.\odin.ps1 project tree . --root "backend/app" --format markdown

# Remove Vault's imported index; repository files are never deleted
.\odin.ps1 project remove .
```

Odin never executes imported code and never writes into the registered repository. Scope changes build a candidate snapshot while the last usable snapshot remains active. Graph and tree views stay out of the way until you explicitly request them.

## How retrieval works

Vault uses retrieval-augmented generation rather than training a model on each cluster.

For every grounded question, Vault:

1. identifies the relevant vault and retrieval scope;
2. searches indexed source chunks;
3. selects and deduplicates the strongest evidence;
4. adds useful working memory and cluster profile information;
5. trims the packet to a bounded token budget;
6. sends that packet to the configured synthesis model;
7. returns the answer with citations and warnings when evidence is incomplete.

Retrieval remains the authority for names, dates, numbers, source IDs, and citations. SQLite is the source of truth; embeddings and vector indexes are derived state that can be rebuilt.

## Local-first by design

Vault's privacy model is based on explicit boundaries:

- You choose the vault folder.
- You choose which sources are added.
- Plaintext content is not intentionally sent anywhere unless you configure or approve an external model or tool.
- Bridge and MCP access are authenticated and limited to the context surfaces they expose.
- Imported code is treated as untrusted input and is not executed.
- Removing an Odin project removes Vault's index, not the original repository.

Local-first does not mean every optional model runs locally. It means Vault owns the context boundary and makes external access deliberate.

## Bridge and external tools

Vault can provide approved context to other applications without handing them an entire vault dump.

The current integration surfaces are:

- a local Bridge HTTP API
- an MCP server
- PowerShell and Python command-line helpers
- browser-extension capture flows

Bridge returns shaped context packets containing relevant citations, snippets, memory items, cluster profiles, token estimates, and warnings. This lets another model work with the same evidence as Vault's own chat.

Development entry points:

```powershell
$env:CML_BRIDGE_TOKEN = "<bridge-token>"
.\scripts\bridge\cml-bridge.ps1 "What changed in the project plan?"
.\.venv\Scripts\python.exe -m backend.app.bridge_mcp
```

## Install from source

### Requirements

- Windows 10 or later
- Node.js 18 or later
- Python 3.11 or later
- Git

### 1. Clone the repository

```powershell
git clone https://github.com/csshlok/CML.git
cd CML
```

### 2. Install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e backend
npm install
```

### 3. Configure the environment

```powershell
Copy-Item .env.example .env
```

The default development configuration is local. Common overrides include:

- `CML_DATA_DIR` — local application-data directory
- `CML_DATABASE_PATH` — SQLite database location
- `CML_MODELS_DIR` — local model directory
- `CML_API_TOKEN` — desktop-to-backend authentication token
- `CML_EMBEDDING_PROVIDER` — embedding runtime selection

### 4. Start Vault

Open two PowerShell terminals from the repository root.

Backend:

```powershell
npm run backend
```

Electron desktop app:

```powershell
npm run dev
```

The backend listens on `http://127.0.0.1:7343`. The renderer development server uses `http://127.0.0.1:5173`, but normal use should go through the Electron window launched by `npm run dev`.

### 5. Check backend health

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:7343/health
```

## Benchmarks

Vault is evaluated on two public conversational-memory benchmarks. LongMemEval tests memory across long, multi-session histories; LoCoMo tests evidence retrieval and question answering over extended conversations. Odin is not involved in these runs, so the results below measure Vault's memory and context pipeline.

### Latest headline results

| Benchmark and configuration | Questions | Retrieval | Kimi K2.6 | GPT-5.4 judge | Reader prompt tokens/query | Evaluation cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| LongMemEval-S, claim-first 10K | 500 | 0.9802 recall@10 | 81.8% | 82.0% | **8,307.1** | **$4.5111** |
| LoCoMo, ColBERT | 1,540 | **0.7606 recall@10** | **66.75%** | **63.96%** | **650.4** | **$1.7388** |

The claim-first LongMemEval pipeline is Vault's recommended measured configuration. Compared with the previous full-context baseline, it reduced reader prompts by **75.08%**, evaluation cost by **66.39%**, and mean reader latency by **60.68%**. All 500 questions remained within the 10,000-token packed-prompt budget. Historical configurations and their accuracy-efficiency tradeoffs remain documented in the [full benchmark report](BENCHMARK.md).

### What that means in a working day

| If you ask 100 context-heavy questions | Claim-first Vault | Saving from the previous full-context baseline |
| --- | ---: | ---: |
| Reader prompt volume | 0.83M tokens | **2.50M fewer tokens (75.08%)** |
| Sequential reader wait, at benchmark latency | 7.5 minutes | **11.5 minutes less (60.68%)** |
| Benchmark reader + dual-judge cost | $0.90 | **$1.78 less (66.39%)** |

In practical terms, the measured claim-first pipeline can answer about **4× as many similarly sized questions within the same reader-prompt token allowance**, with roughly **82 accepted answers per 100 benchmark questions** under both evaluation perspectives. These are benchmark projections, not a promise about every personal vault: actual savings depend on source length, question complexity, model pricing, caching, and whether an application runs judges at all.

On LoCoMo, the full ColBERT retrieval pass improved recall@10 from 0.6295 to 0.7606 and reduced questions with no annotated evidence in the top 50 from 217 to 100. On the exact earlier 300-question set, that retrieval change raised official token F1 from 0.4373 to 0.5065, Kimi acceptance from 59.33% to 66.00%, and GPT-5.4 acceptance from 56.33% to 63.33%.

### Cost and comparison boundary

Vault's ingestion used local embeddings and consumed **zero billable API ingestion tokens**. The costs above cover answer generation and two judges, not ordinary local retrieval. They are estimates from recorded provider usage and the prices verified when the runs were completed.

Published systems currently report higher LongMemEval answer accuracy, but the results are not a shared leaderboard: readers, judges, context accounting, reasoning settings, and retrieval limits differ.

| System | Published LongMemEval result | Reported context |
| --- | ---: | ---: |
| [Mem0](https://mem0.ai/research) | 94.4% on 500 questions | 6,787 mean tokens |
| [Hindsight](https://vectorize.io/benchmarks) | 94.6% current published LongMemEval result | Not published with the headline |
| [Zep](https://www.getzep.com/research/) | 90.2% on 500 questions | 4,408 median tokens |
| **Vault claim-first 10K** | **82.0% independent judge on 500 questions** | **8,307 mean complete reader-prompt tokens** |
| [Graphify](https://github.com/Graphify-Labs/graphify#benchmarks) | 76% on 50 questions | Not published |

Vault is not yet state of the art in multi-session answer accuracy. Its measured advantages are local-first ingestion with no extraction-API bill, a reproducible dual-judge protocol, bounded and inspectable evidence packets, and one workspace for conversational, document, and Odin project context.

Read [Benchmark methodology and full analysis](BENCHMARK.md) for historical baselines, category results, token and cost accounting, confidence information, rejected experiments, retrieval variants, competitive caveats, and artifact locations.

## Architecture

Vault runs as two cooperating local processes:

| Component | Responsibility |
| --- | --- |
| Electron + React desktop app | User interface, onboarding, vault selection, and desktop integration |
| FastAPI backend | Ingestion, storage, retrieval, clustering, memory, Bridge, security boundaries, and Odin |
| SQLite | Authoritative vault metadata and content records |
| Vector index | Rebuildable semantic-search state |
| Browser extension | Thin capture surface for supported browsers |

Repository layout:

```text
apps/
  desktop/             Electron shell and React interface
  browser-extension/   Browser capture client
backend/               FastAPI application and retrieval system
docs/                  Product, architecture, UI, and operational docs
requirements/          Python dependency manifests
scripts/               Development, benchmark, security, and packaging tools
```

For deeper detail, start with [Project Context](docs/PROJECT_CONTEXT.md), [Architecture](docs/ARCHITECTURE.md), and [Working Commands](docs/WORKING_COMMANDS.md).

## Development

Run the main validation checks before committing:

```powershell
npm run lint
npm run build
.\scripts\backend\run-tests.ps1 -Tier quick
.\scripts\backend\run-tests.ps1 -Tier integration
.\scripts\backend\run-tests.ps1 -Tier system
.\scripts\backend\run-tests.ps1 -Tier benchmark
.\.venv\Scripts\python.exe -m compileall -q backend\app scripts\backend backend\tests
npm run security:renderer
```

The 50,000-file scale tier is intentionally manual because it has a longer Windows runtime budget:

```powershell
.\scripts\backend\run-tests.ps1 -Tier scale
```

Build a Windows package with:

```powershell
npm run package:win
```

Packaging and clean-machine validation are still active release-hardening work. See [Working Commands](docs/WORKING_COMMANDS.md) for smoke tests, benchmarks, packaging modes, and versioning.

## Status and roadmap

The core local workflow is implemented: vaults, ingestion, indexing, retrieval, grounded chat, clusters, memory, Bridge/MCP delivery, and the Odin foundation.

Before a public V1 release, the project still needs:

- clean-machine Windows installer validation
- signed-installer and Windows account-separation proof
- broader external graph-quality and parser-performance evaluation
- additional accessibility and interaction QA
- continued packaging and security hardening

Do not use this pre-release build as the only copy of important data.

## FAQ

### Does Vault upload my entire library to an AI provider?

No. Vault indexes explicitly added sources locally and builds focused context packets. Content only crosses a local boundary when you configure or approve an external integration that needs it.

### Does Vault train a model on my files?

No. The live architecture is retrieval-based. Vault finds relevant evidence and supplies it to the configured model for synthesis.

### Can Vault use local models?

Yes. Vault supports local model configuration. If no synthesis runtime is available, grounded retrieval can still return a retrieval-draft response instead of pretending a generated answer succeeded.

### Does Odin modify or execute my repository?

No. Odin reads approved project files to build its index. It does not execute imported code, and project removal only deletes Vault's imported state.

### Is macOS or Linux supported?

Not for V1. Windows is the current public target.

### Is there a stable installer?

Not yet. Source setup is the supported path while packaging and clean-machine validation are completed.

## License

Vault is available under the [MIT License](LICENSE).
