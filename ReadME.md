<p align="center">
  <img src="apps/desktop/public/brand/Frame%208.png" width="420" alt="Vault">
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
  <a href="https://github.com/csshlok/CML/releases/latest"><img src="https://img.shields.io/badge/release-v0.1.14-2563eb.svg" alt="Latest release v0.1.14"></a>
  <img src="https://img.shields.io/badge/storage-local--first-2f855a.svg" alt="Local-first storage">
</p>

Vault gives AI a durable memory outside the chat window. Add the material you already work with, organize it around the way you work, and ask questions in plain language. Vault returns answers grounded in your sources, with citations you can inspect.

It is a local-first Windows desktop app, a retrieval system, and a controlled bridge between your private context and the AI tools you choose to use. A configurable Home workspace keeps active work, imports, recent sources, clusters, projects, and conversations within reach without turning the app into a crowded dashboard.

Chat does not force every question through retrieval. General questions go directly
to the selected model. Questions about saved material receive a bounded evidence
packet, and the model is told how strong and trustworthy that evidence is: sufficient
evidence supports a grounded answer, weak but relevant evidence permits qualified
reasoning, contradictory evidence must be explained, and hostile source text cannot
take control of the answer. Profile questions can use trusted local profile facts
without treating previous assistant replies as personal memory.

> [!IMPORTANT]
> Vault is pre-release software. A Windows installer is available from the
> [latest GitHub release](https://github.com/csshlok/CML/releases/latest), but it
> is not yet code-signed or qualified on the full clean-machine matrix. Keep a
> separate backup of important data.

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
- **Import files naturally** with the file picker, folder import, or desktop drag and drop.
- **Track large imports from any screen** with file counts, percentage, current-file details, and controls to pause, resume, or stop safely.
- **Ask grounded questions** and inspect the source passages used to answer them.
- **Use the selected model's own reasoning** for general questions and qualified analysis when retrieved evidence is relevant but incomplete.
- **Group related work into clusters** for projects, clients, research topics, or areas of responsibility.
- **Create, delete, and reorganize clusters**, or move ready and unclustered sources into a cluster without reorganizing the rest of the vault.
- **Search across your context** without remembering where a detail was originally stored.
- **Accelerate large-vault retrieval automatically** after a per-vault TurboVec quality and performance gate passes, with exact search retained as the safe fallback.
- **Shape Home around your workflow** with Focused, Library, and Activity presets, type and sort controls, density choices, and reorderable sections.
- **Continue where you left off** across recently opened sources, chats, clusters, and projects.
- **Index codebases with Odin** and ask how a project works without browsing every file manually.
- **Request graphs and trees when needed** while keeping the normal interface focused on useful summaries and answers.
- **Connect ChatGPT and other tools deliberately** through authenticated Bridge, MCP, the local API, and approved command-line clients.
- **Use a profile that stays consistent** across onboarding, Settings, and the sidebar, including your display name and profile photo.
- **Keep control of your data** with explicit vault locations, local storage, and reviewable access boundaries.

## A typical workflow

1. Create a vault in a folder you control.
2. Add files, folders, links, notes, screenshots, or a code project.
3. Follow ingestion progress while Vault extracts the content, creates searchable chunks, and builds a local index.
4. Pause or resume a large import when needed without losing confirmed work.
5. Organize related sources into clusters, move individual sources, or let Vault suggest useful groupings. Ready sources that do not yet meet conservative automatic-placement thresholds remain visibly unclustered.
6. Ask a question from Home or Chat, scoped to the complete vault or a selected cluster.
7. Vault decides whether the question needs no retrieval, trusted local context, or a bounded evidence packet.
8. The selected model answers directly or synthesizes the evidence under the applicable trust and sufficiency policy.
9. Grounded answers include citations so you can inspect the original material.

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

Files can be selected normally or dropped into the desktop app from File Explorer. Every source remains reviewable and removable. Vault does not silently scan your device.

## Odin: understand a codebase without reading all of it

Odin is Vault's project-context layer. It registers a repository as a first-class project, indexes its files, extracts deterministic structure, connects it to retrieval, and exposes the result to Vault and approved outside tools.

You can add a project without installing the command line. Open **Projects**, choose
**Add project folder**, and select one or more folders. Vault starts indexing them
immediately. Odin is the optional terminal workflow for adding, synchronizing, and
querying the same projects from an IDE or PowerShell.

### Install the Odin command

Vault offers two installation methods in **Settings > Odin command**:

- **Install Odin — recommended:** Vault creates and maintains the Windows launcher in your local application-data folder and adds that folder to your user `PATH`. Use **Repair Odin** from the same screen if the launcher is moved or damaged.
- **Install with uv:** Vault installs the packaged Odin command as an isolated Python tool with `uv`. This is useful when you already manage command-line tools with `uv`; `uv` must be installed and available on `PATH`.

Both methods install the same command and connect to the currently running Vault desktop app. After installation, open a new PowerShell window and verify it:

```powershell
odin --help
```

Select **Pair Odin** in Settings. Vault opens PowerShell for the pairing request; approve the waiting computer in **Odin command-line access**. You can then verify the protected connection:

```powershell
odin auth status
```

Pairing is separate from installation. Reinstalling Odin does not grant access to a library, and connected computers can be rotated or revoked from Settings.

When running Vault from a source checkout, `.\odin.ps1` provides the same commands without installing a global launcher. Otherwise, run Odin from a project folder:

```powershell
odin project add . --name "My Project" --scope context
```

The default `context` scope includes source code plus useful repository documentation and configuration. Use `--scope code` when you want a source-focused index, or change the persisted choice during a later sync:

```powershell
odin project add . --name "My Project" --scope code
odin project sync . --scope context
```

Then ask questions or inspect the project:

```powershell
# See registered projects and indexing state
odin project list
odin project status .

# Update or rebuild the index
odin project sync .
odin project reindex . --layer retrieval

# Ask about the project
odin context "How does authentication work?" --project .
odin project explain . register_project
odin project path . register_project build_structure_graph

# Request structural output
odin project graph . --query "project indexing" --depth 2 --format markdown
odin project tree . --root "backend/app" --format markdown

# Remove Vault's imported index; repository files are never deleted
odin project remove .
```

Odin never executes imported code and never writes into the registered repository. Scope changes build a candidate snapshot while the last usable snapshot remains active. Graph and tree views stay out of the way until you explicitly request them. Registered computers and command-line clients remain visible and revocable in Settings.

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

- a guided ChatGPT connection with authenticated secure-tunnel support
- a local Bridge HTTP API
- an MCP server
- approved Odin, PowerShell, and Python command-line clients
- browser-extension capture flows

Bridge returns shaped context packets containing relevant citations, snippets, memory items, cluster profiles, token estimates, and warnings. This lets another model work with the same evidence as Vault's own chat.

Connections start with explicit approval and a visible capability profile. Read-only access can retrieve approved context without changing the vault. Read/write access remains a separate choice, and incoming captures can be held for review before they become trusted reusable context. Credentials stay protected by the operating system and can be rotated or revoked from Vault.

Development entry points:

```powershell
$env:CML_BRIDGE_TOKEN = "<bridge-token>"
.\scripts\bridge\cml-bridge.ps1 "What changed in the project plan?"
.\.venv\Scripts\python.exe -m backend.app.bridge_mcp
```

## A workspace that stays out of the way

Home is designed as a working overview rather than a wall of equal-sized cards. The default Focused layout keeps Ask Vault, items that need attention, recent work, active clusters, and a small quick-action row in view. Library and Activity presets reveal more browsing or operational detail when needed.

Type and Sort controls change the sources shown across the overview. Customize opens a compact panel for choosing a preset, comfortable or compact density, list or grid presentation, visible sections, and section order. These choices are saved for the active profile.

Long-running ingestion remains visible after leaving Sources. The compact progress notice shows processed and total files, percentage, and the current file. It can be dismissed without cancelling the job, paused and resumed safely, or stopped after confirmation. The Sources detail panel stays closed until a source is selected, leaving the default workspace open for browsing.

Projects and imported folders with 20 or more indexed files appear as folders in
Sources instead of filling the main list with hundreds of rows. Open a folder to
browse, filter, inspect, reindex, open, or remove its individual files. Files from a
new project snapshot remain hidden until that snapshot is ready, so an in-progress
update does not create temporary duplicates or unclustered entries.

Vault also keeps routine feedback lightweight. Successful saves, connection results, and other short updates appear as small notifications at the bottom of the app window and fade automatically. A locked library can be unlocked on the same screen; reset and recovery remain in Privacy settings. Press **Ctrl+L** or choose **Lock library** in the command palette to lock immediately. Incorrect passphrases are shown beside the field. Imported models are reconciled before they are shown as ready, and duplicate model registrations are prevented from appearing as separate working installations.

Settings gives each feature one clear location, keeps explanations directly below
their headings, and places longer technical detail behind optional disclosures.
Display-name and profile-photo changes are shared with the sidebar instead of
creating a second profile state. Grounded chat confirms that a completed answer is
stored locally before reporting success.

Startup and recovery screens use the same Vault identity as onboarding and the sidebar. If Vault cannot open, the recovery screen gives a short explanation, offers a safe next step, and keeps technical diagnostic details available to copy without placing them in the main message.

## Install on Windows

The current public build is **Vault v0.1.14**.

1. Open the [latest GitHub release](https://github.com/csshlok/CML/releases/latest).
2. Download `test-0.1.14-Setup.exe`.
3. Run the installer and choose a user-writable installation folder.
4. Create a new library or select an existing Vault library during onboarding.

GitHub publishes the SHA-256 digest with the release asset. The release also
contains the matching Electron blockmap used for update metadata. Windows may
show an unknown-publisher warning because public code signing remains release
work.

## Install from source

### Requirements

- Windows 10 or later
- Node.js 22
- Python 3.11 through 3.14; Python 3.12 x64 is recommended
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

Vault is evaluated on two public suites. LongMemEval tests memory across long, multi-session histories, while Open RAG Bench tests retrieval and grounded QA over scientific documents containing text, images, and tables. Odin is not involved in these runs, so the results below measure Vault's retrieval, evidence-packing, and answer pipeline.

### Latest headline results

| Benchmark and configuration | Questions | Retrieval | Kimi K2.6 | GPT-5.4 judge | Reader prompt tokens/query | Evaluation cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Open RAG Bench, frozen QA prefix pilot | 500 | 0.9380 section Hit@10 | **83.8%** | **73.6%** | **2,672.1** | **$1.9102** |
| LongMemEval-S, claim-first 10K | 500 | 0.9802 recall@10 | 81.8% | 82.0% | **6,922.5** | **$4.5111** |

The claim-first LongMemEval pipeline is Vault's recommended measured configuration. The latest packet replay averaged **6,922.5 reader prompt tokens/query**, a **79.23%** reduction from the previous full-context baseline. The recorded full evaluation reduced cost by **66.39%** and mean reader latency by **60.68%**. Historical configurations and their accuracy-efficiency tradeoffs remain documented in the [full benchmark report](BENCHMARK.md).

On all **3,045 Open RAG Bench queries**, Vault reached **64.04% section Hit@1**, **90.11% Hit@5**, **94.84% Hit@10**, and **99.61% document Hit@10**, with **1.060 seconds mean retrieval latency**. The paid QA gate intentionally stopped after the frozen first 500 questions: Kimi accepted 83.8% of answers, GPT-5.4 accepted 73.6%, judge agreement was 86.2%, and the reader used 2,672.1 prompt tokens per question. The lower token count is a useful result for this document-QA workload, but it is not a direct improvement over LongMemEval's 6,922.5 because the datasets and context shapes differ.

### What that means in a working day

| If you ask 100 context-heavy questions | Claim-first Vault | Saving from the previous full-context baseline |
| --- | ---: | ---: |
| Reader prompt volume | 0.69M tokens | **2.64M fewer tokens (79.23%)** |
| Sequential reader wait, at benchmark latency | 7.5 minutes | **11.5 minutes less (60.68%)** |
| Benchmark reader + dual-judge cost | $0.90 | **$1.78 less (66.39%)** |

In practical terms, the measured claim-first pipeline can answer about **4.8× as many similarly sized questions within the same reader-prompt token allowance**, with roughly **82 accepted answers per 100 benchmark questions** under both evaluation perspectives. These are benchmark projections, not a promise about every personal vault: actual savings depend on source length, question complexity, model pricing, caching, and whether an application runs judges at all.

### Cost and comparison boundary

Vault's ingestion used local embeddings and consumed **zero billable API ingestion tokens**. The costs above cover answer generation and two judges, not ordinary local retrieval. They are estimates from recorded provider usage and the prices verified when the runs were completed. Open RAG's $1.9102 is the sum of its recorded reader and judge component estimates; a stale aggregate field in that artifact incorrectly remained zero and is not used.

Third-party product results are intentionally omitted because their readers, judges,
context accounting, reasoning settings, retrieval limits, and sample sizes are not
matched to this protocol. Vault's measured LongMemEval result is **82.0%** by the
independent judge on 500 questions with **6,922.5 mean reader-prompt tokens**.

Vault's measured advantages are local-first ingestion with no extraction-API bill,
a reproducible dual-judge protocol, bounded and inspectable evidence packets,
strong document-level retrieval on an external scientific corpus, and one workspace
for conversational, document, and project context. Open RAG's first-500 QA result
is a deterministic prefix pilot rather than a random sample or completed
3,045-question QA run.

Read [Benchmark methodology and full analysis](BENCHMARK.md) for historical baselines, category results, token and cost accounting, confidence information, rejected experiments, retrieval variants, competitive caveats, and artifact locations.

## Architecture

Vault runs as two cooperating local processes:

| Component | Responsibility |
| --- | --- |
| Electron + React desktop app | Frameless Windows shell, user interface, onboarding, vault selection, and desktop integration |
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
requirements/          Python dependency manifests
scripts/               Development, benchmark, security, and packaging tools
```

For measured behavior, methodology, and reproducibility details, see the
[benchmark report](BENCHMARK.md).

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

Release builds run the renderer build, stage the local helper runtimes, audit the
package layout, and verify the unpacked executable and installer before publication.

The current source includes the frameless Windows shell, durable import controls,
profile-synced Home preferences, managed-model reconciliation, native file drops,
branded recovery screens, Odin command-line installation, and the guided ChatGPT
MCP connection. Published installers are built from tagged release revisions.

## Status and roadmap

The core local workflow is implemented: vaults, durable ingestion, indexing,
retrieval, grounded chat, clusters, source moves, memory, configurable Home
workspaces, Bridge/MCP delivery, approved command-line access, and Odin projects.

The latest tagged build is **v0.1.14**. The current security and stability
remediation includes durable job recovery, bounded watched-folder reconciliation,
Bridge scope enforcement, resumable encryption and embedding transitions, bounded
retention, long-session UI ownership, scale gates, and packaged-runtime validation.

Before a public V1 release, the project still needs:

- completion of the 72-hour mixed-workload soak qualification
- clean-machine Windows installer validation across the supported account matrix
- signed-installer and Windows account-separation proof
- broader external graph-quality and parser-performance evaluation
- additional accessibility and interaction QA
- continued release-candidate packaging and recovery testing

Do not use this pre-release build as the only copy of important data.

## FAQ

The complete [Vault FAQ](FAQ.md) mirrors all **74 questions** available in the
in-app **Help** screen, including setup, imports, search, chat, clusters, Odin,
maps, tasks, models, OCR, backups, Bridge, privacy, security, and troubleshooting.

For the most current interactive guidance, open **Help** inside Vault. The Markdown
FAQ is maintained as the repository-readable equivalent for GitHub users.

## License

Vault is available under the [MIT License](LICENSE).
