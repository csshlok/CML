# Vault Onboarding PRD

Last updated: 2026-05-31

## Purpose

Onboarding should get a first-time Windows user from installed app to a usable local vault with the least possible friction. It should feel like a clean Apple setup flow: calm, minimal, precise, and trustworthy.

The user should finish onboarding knowing three things:

- where their vault data is stored
- which local embedding model powers memory search
- whether Vault is ready to ingest sources and answer with local context

## Product Principles

- One decision per screen.
- No technical dashboard language in the default path.
- Exact storage paths must be visible before the user commits.
- Embedding setup is required before entering the main app.
- Source ingestion starts only after the full vault backend owns the chosen vault folder.
- The app name shown in the window and setup flow is always `Vault`.
- Hash/deterministic embeddings are never offered in production onboarding.
- The flow should look native, quiet, and intentional, not like an installer wizard or download manager.

## Non-Goals

- Do not build a marketing landing page.
- Do not ask users to understand vectors or embedding internals.
- Do not ingest files in pre-vault mode.
- Do not require synthesis model setup before the user can enter Vault, unless the final V1 policy changes. Embeddings are compulsory; synthesis runtime can be configured during onboarding or later with a visible runtime state.
- Do not bundle multi-GB LLM weights inside the installer.

## Current Visual System

The onboarding UI must use the existing desktop design tokens from `apps/desktop/src/styles.css`. New colors should be added only as semantic OKLCH tokens, not raw hex values.

### Core Tokens

| Role | Current Token | Value | Usage |
| --- | --- | --- | --- |
| App background | `--background` | `oklch(0.985 0.005 80)` | Full onboarding canvas |
| Text | `--foreground` | `oklch(0.22 0.02 60)` | Primary copy |
| Card/surface | `--card` | `oklch(0.995 0.004 80)` | Small setup  only |
| Primary action | `--primary` | `oklch(0.48 0.06 50)` | Continue, finipanelssh, selected option |
| Secondary surface | `--secondary` | `oklch(0.955 0.012 80)` | Quiet option backgrounds |
| Muted text | `--muted-foreground` | `oklch(0.5 0.015 70)` | Supporting copy |
| Accent surface | `--accent` | `oklch(0.93 0.02 80)` | Hover/selected subtle fill |
| Border/input | `--border`, `--input` | `oklch(0.9 0.012 75)` | Hairline separators and inputs |
| Focus ring | `--ring` | `oklch(0.55 0.04 60)` | Keyboard focus |
| Destructive | `--destructive` | `oklch(0.58 0.14 25)` | Blocking setup errors |

### Cluster And Status Accents

Use these only as small accents, not dominant backgrounds:

- Sage: `--cluster-sage: oklch(0.82 0.05 150)`
- Sand: `--cluster-sand: oklch(0.85 0.05 80)`
- Sky: `--cluster-sky: oklch(0.83 0.05 230)`
- Blush: `--cluster-blush: oklch(0.85 0.05 20)`
- Lavender: `--cluster-lavender: oklch(0.83 0.04 300)`
- Terracotta: `--cluster-terracotta: oklch(0.78 0.07 40)`
- Ready: `--status-ready: oklch(0.62 0.1 150)`
- Learning: `--status-learning: oklch(0.72 0.12 70)`
- Issue: `--status-issue: oklch(0.6 0.14 25)`
- Paused: `--status-paused: oklch(0.65 0.01 70)`

### Layout And Component Rules

- Use a centered setup column with generous whitespace.
- Maximum content width: `680px` for normal steps, `820px` only for model-choice comparisons.
- Use `8px` radius or less for cards/buttons, matching `--radius: 0.5rem`.
- Prefer hairline separators over boxed panels.
- Use icons only where they clarify the action: folder, check, download, plug, warning.
- Avoid nested cards.
- Avoid loud gradients, bokeh, decorative blobs, or oversized hero art.
- Typography uses the current app stack: `Inter`, `ui-sans-serif`, `system-ui`, `sans-serif`.
- No negative letter spacing and no viewport-scaled font sizes.

## Flow

### Step 1: Welcome

Goal: make the user understand this is local and private without turning it into marketing.

Required UI:

- Title: `Set up Vault`
- Short copy: `Create a local memory space for your files, links, notes, and chats.`
- Primary action: `Continue`
- Secondary detail: `Your data stays on this device unless you choose a synced folder.`

No account creation, sign-in, or cloud pitch.

### Step 2: Choose Vault Location

Goal: create the real storage boundary before any data ingestion.

Required fields/actions:

- Vault name
- Vault folder picker
- Exact resolved data path preview: `<selected folder>\.vault`
- Disk-space preflight result
- Primary action: `Create vault`

Backend behavior:

- Electron starts in `pre_vault` mode before this step completes.
- No ingestion, chat, clustering, or source routes are allowed in `pre_vault`.
- After selection, Electron stores the active vault folder, shuts down the pre-vault backend, and restarts the backend with:
  - `CML_BACKEND_MODE=full_vault`
  - `CML_DATA_DIR=<selected folder>\.vault`
  - `CML_DATABASE_PATH=<selected folder>\.vault\cml.sqlite3`
- The full backend must pass startup gates before onboarding continues.

Error states:

- Folder unavailable
- Permission denied
- Disk space too low
- Backend failed to restart
- Vault lock conflict

### Step 3: Set Up Memory Search

Goal: require a real local embedding model before users enter the main app.

User-facing label: `Set up memory search`

Required options:

- `Use Vault's recommended model`
- `Use a model already on this device`

Recommended default:

- `sentence-transformers/all-MiniLM-L6-v2` as the current development candidate until final V1 embedding model selection is locked.

Requirements:

- The user cannot continue until a test embedding succeeds.
- The UI must show where the model will be stored or which local path/runtime is being used.
- The UI must show approximate download size and disk-space impact before download.
- The user must be able to cancel an active model download.
- Hash embeddings do not appear as an option.
- The installer does not bundle MiniLM or other embedding weights. The user must download Vault's recommended embedding model after installation or link an existing local cache/model path.

Success state:

- `Memory search ready`

Failure states:

- Model missing
- Download failed
- Test embedding failed
- Disk space too low
- Unsupported model path

### Step 4: Connect Local Chat Model

Goal: let users configure the LLM chatbot/runtime without blocking the whole product on first run.

User-facing label: `Connect local chat`

Options:

- `Use Vault's recommended chat model`
- `Connect existing local runtime`
- `Set up later`

Recommended model ladder remains:

- Qwen3 4B Q4_K_M as default recommendation
- Phi-4 Mini Instruct Q4_K_M as low-spec fallback
- Qwen3 8B Q4_K_M as quality option

Requirements:

- If configured, the setup must test the OpenAI-compatible endpoint before marking chat ready.
- If skipped, the app enters with a visible `Local chat model not connected` state.
- General chat should not silently pretend it is grounded if retrieval/model setup is unavailable.

### Step 5: Add First Sources

Goal: give the user a useful vault without forcing import during setup.

Allowed actions:

- Add files
- Add folder
- Add link
- Paste text
- Skip for now

Rules:

- This step only runs after the full-vault backend is ready.
- Supported source types and failures must be shown in plain language.
- Import progress should show current task and counts, not a fake progress bar.
- If embeddings become unavailable, ingestion blocks with an explicit setup-needed message.

Copy examples:

- `Drop files, notes, screenshots, PDFs, or links.`
- `Vault will index them locally so chat and search can use them.`

### Step 6: Open Vault

Goal: transition into the real app.

Destination:

- Mind workspace, not chat and not a landing page.

Required ready summary:

- Vault path
- Memory search status
- Local chat status
- Imported item count
- Any blocked setup items

Primary action:

- `Open Vault`

## Startup And Repair UX

Onboarding must consume structured startup status from `startup-status.json` and map phases to user-facing states.

Required messages:

- `Preparing Vault...`
- `Checking vault health...`
- `Opening your vault...`
- `Vault needs attention`
- `Memory search needs setup`

If SQLite integrity check or schema migration fails, onboarding must not show generic backend-offline UI. It should show a repair screen with:

- exact vault path
- failure summary
- diagnostic export action
- retry startup action
- clear warning if data may be unrecoverable

## Copy Guidelines

Use short direct copy.

Preferred terms:

- `Vault`
- `Memory search`
- `Local chat`
- `Sources`
- `Clusters`
- `Ready`
- `Needs setup`

Avoid in default UI:

- embeddings
- vectors
- model-provider internals
- schema
- backend
- database

Advanced details may expose technical terms when needed for setup or debugging.

## Acceptance Criteria

- Fresh install starts in restricted `pre_vault` mode.
- No vault/source/chat/search/cluster data can be created in `pre_vault` mode.
- User-selected vault folder becomes the real storage root.
- UI shows the exact resolved `.vault` data path before creation.
- Full-vault backend restarts with the selected data directory.
- Startup failure reasons are specific, not generic `backend unavailable`.
- Embedding setup is compulsory and must pass a real test embedding.
- Hash embeddings are hidden from production onboarding.
- Model download has visible size, destination, progress, and cancel.
- Source ingestion begins only after full-vault backend readiness.
- User can skip first import.
- User lands on Mind workspace after setup.
- The flow uses the current OKLCH design tokens and feels native, calm, and minimal.

## Open Implementation Items

- Finalize V1 embedding model recommendation and non-bundled download/link strategy.
- Add disk preflight for vault path and model downloads.
- Add model download progress/cancel UI for onboarding.
- Add startup repair screen that reads structured startup status.
- Add embedding setup health check that runs on every launch, not only first run.
- Store setup profile values in backend settings instead of local storage only.
- QA the flow in dev and packaged Windows builds.
