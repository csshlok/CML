# CML UI Audit Brief

Last updated: 2026-06-08

## Purpose

This document is a full UI audit and design handoff brief for CML.

It is written so a product/UI designer can redesign the application without seeing the current backend, current frontend code, or current app build.

The goal is to define:

- every page and major surface the app needs
- the information each surface must show
- the interactions that must exist
- the states each surface must support
- the user-facing language the product should use

This is a product/UI inventory, not an implementation spec.

## Product Summary

CML is a local-first Windows desktop app for building a personal knowledge vault.

The user creates a local vault, adds files/folders/links/notes/images/PDFs/chats, and the app:

- ingests and extracts content locally
- indexes it for search
- groups related material into clusters
- lets the user explore the vault visually
- answers questions with citations from vault content
- optionally exposes approved context to external tools through Bridge

The app should feel like a calm memory workspace, not a technical AI dashboard.

## Core Product Language

Use these user-facing terms consistently:

| Internal idea | User-facing term |
| --- | --- |
| database | Vault storage |
| embedding model | Memory search |
| vector index | Search index |
| model runtime | Local chat |
| LoRA adapter | Local expert |
| fine-tuning | Learning |
| background job | Task |
| backend unavailable | Vault is not ready |
| pre-vault mode | Setup mode |
| full-vault mode | Vault open |

Preferred status labels:

- `Ready`
- `Learning`
- `Needs setup`
- `Needs update`
- `Paused`
- `Issue`
- `Offline`
- `Blocked`

Avoid technical language in the default path unless the user opens advanced details.

## Global App Structure

The desktop app should be designed as a persistent workspace with these regions:

- Left sidebar
- Main content area
- Optional right inspector panel
- Footer/status strip
- Global command palette
- Modal/dialog layer

## Global Surfaces

### 1. App Shell

Purpose:

- persistent navigation and workspace structure

Must show:

- app mark and product name `Vault`
- active vault name
- truncated active vault path
- primary navigation
- utility navigation
- recent clusters
- recent or saved chats
- compact footer status

Main interactions:

- switch tabs
- open command palette
- jump to recent cluster
- jump to recent chat
- open settings

States:

- no active vault
- active vault
- backend checking
- backend degraded
- backend offline
- narrow window / collapsed sidebar

### 2. Footer Status Strip

Purpose:

- low-noise always-visible system status

Must show:

- active vault path or `No active vault`
- backend state
- task state summary
- local/privacy statement
- shortcut hints

States:

- healthy
- busy
- degraded
- blocked

### 3. Global Command Palette

Purpose:

- fast action launcher and global navigation

Must include groups:

- Actions
- Go to
- Clusters
- Sources
- Chats
- Diagnostics and utility actions

Required actions:

- New chat
- Add files
- Add folder
- Add link
- Paste text
- Open vault
- Create vault
- Go to Mind
- Go to Sources
- Go to Clusters
- Go to Map
- Go to Chat
- Go to Bridge
- Go to Settings
- Export diagnostics

States:

- empty results
- disabled action with explanation
- no active vault

## Startup And Entry Flows

These are first-class UI surfaces and should be designed explicitly, not treated as edge cases.

### 4. Splash / Startup Progress

Purpose:

- show that the app is opening and checking local state

Must show:

- app mark
- `Opening Vault`
- current startup step in plain language
- calm progress indicator

User-facing startup phases:

- Preparing Vault
- Checking vault health
- Opening your vault
- Starting memory search
- Ready

Should not show:

- raw internal phase names
- raw file paths unless user opens details
- fake percentage bars

### 5. Startup Repair / Failure Page

Purpose:

- structured failure state when the app cannot open safely

Must show:

- app mark
- title like `Vault needs attention before it can open`
- human-readable failure summary
- current phase/state
- active data directory
- database path
- startup-status file path in advanced/copy details
- recovery guidance

Required actions:

- Try again
- Copy details
- Export diagnostics
- Open anyway only for lock-conflict cases
- Close Vault

Failure types to design for:

- vault lock conflict
- failed vault health check
- schema/migration failure
- helper/runtime verification failure
- backend never reached ready
- disk space unavailable
- path/permission issue

### 6. No Vault / Choose Vault Entry State

Purpose:

- app is installed but no real vault is open yet

Must show:

- explanation of what a vault is
- create vault action
- open existing vault action
- privacy/local message

Optional support content:

- examples of what users can add
- where vault data will live

## Onboarding

Onboarding should feel like a calm setup flow, not an installer wizard.

### 7. Onboarding Flow Container

Purpose:

- host the first-run setup sequence

Global elements:

- progress stepper
- persistent setup summary rail
- message area for success/error state
- back/continue controls

### 8. Welcome Step

Must show:

- `Set up Vault`
- what the app does in one short paragraph
- local-only / privacy reassurance

Required action:

- Continue

### 9. Identity / Optional Account Context Step

If retained in V1, keep it minimal.

Must show:

- display name
- optional email or profile label

If removed from V1, omit this screen entirely.

### 10. Vault Location Step

Purpose:

- define the storage boundary before data enters the app

Must show:

- vault name
- vault folder picker
- exact resolved vault data path
- exact resolved SQLite path
- disk space/preflight summary
- warning for synced folders like OneDrive/iCloud/Dropbox if unsafe

Required actions:

- Choose folder
- Create vault

States:

- valid path
- invalid path
- folder unavailable
- permission denied
- low disk space
- lock conflict
- backend restart failed

### 11. Memory Search Setup Step

Purpose:

- configure required local search capability before main use

Must show:

- what memory search means in plain language
- recommended option
- use-existing option
- approximate size
- approximate disk impact
- readiness test status
- where the model will be stored or detected from

Required actions:

- Download recommended
- Choose existing model folder/path
- Test setup
- Retry
- Continue only when ready

States:

- not configured
- download in progress
- download failed
- test failed
- ready

### 12. Local Chat Setup Step

Purpose:

- connect the user-facing local chat runtime

Must show:

- recommended model options by hardware tier
- use existing local runtime
- skip for now if policy allows
- hardware guidance
- disk cost
- expected performance tier

Required actions:

- Download recommended model
- Import/detect existing compatible model
- Activate for chat
- Activate for expert
- Activate approved pair

States:

- no model
- compatible but inactive
- rejected with reason
- downloading
- active for chat
- active for expert
- active pair

### 13. Add First Sources Step

Purpose:

- help the user put real material into the vault immediately

Must show:

- add files
- add folder
- paste text
- add link
- drag-and-drop target
- current import count
- active task status

Required actions:

- Add files
- Add folder
- Paste text
- Add link
- Skip for now

States:

- no items yet
- importing
- queued
- failed item with explanation
- completed import

### 14. Ready Summary / Open Vault Step

Must show:

- vault path
- memory search status
- local chat status
- imported item count
- blocked items if any

Required action:

- Open Vault

## Primary In-App Tabs

### 15. Home / Mind Landing Page

Purpose:

- the first main workspace after setup
- overview of the current vault

Must show:

- page title
- vault summary
- recent memories
- unsorted/unreviewed sources
- health snapshot
- quick actions
- recent activity highlights

Suggested content blocks:

- welcome/summary strip
- recent memories panel
- unsorted items panel
- vault health card
- quick actions card
- recent events card

Required interactions:

- start new chat
- open source
- open cluster
- add source
- create cluster

States:

- no vault
- empty vault
- active vault with low content
- active vault with ongoing ingestion

### 16. Mind / Search Workspace

Purpose:

- search and lightweight ingest workspace

Must show:

- search input
- filters
- sort controls
- add files
- add folder
- add link
- paste note
- drag-and-drop state
- result list
- current vault card
- selected source preview

Filters to support:

- source type
- cluster
- recency
- status
- sort mode

Source row content:

- title
- source type
- short preview
- cluster assignment
- tags
- ingestion/index state
- date

Source inspector/modal must show:

- title
- source type
- extracted preview
- summary
- tags
- cluster
- open/reveal actions
- OCR state if relevant

Required interactions:

- semantic search
- filter results
- sort results
- add files/folders
- add pasted note
- add URL
- inspect source
- open source file
- reveal in folder

States:

- no active vault
- query too short
- no results
- results available
- dragging files over app
- source failed extraction

### 17. Sources Library

Purpose:

- structured table/list view of all source items in the active vault

Layout:

- source list/table left
- source inspector right

Must show in list:

- source title
- source type
- cluster
- ingestion/index state
- date added / updated
- source size proxy if useful

Must show in inspector:

- title
- type badge
- summary / preview
- OCR status
- page count or chunk count
- cluster assignment
- path or URL
- related pages if paginated

Required actions:

- add files
- add folder
- paste text
- add link
- reindex source
- delete source
- open file
- reveal file in folder

States:

- empty library
- no vault
- failed source
- in-progress extraction
- indexed
- needs review

### 18. Clusters Overview

Purpose:

- browse the user’s knowledge spaces

Must show:

- total cluster count
- overall source count
- cluster cards/grid
- suggested cluster actions/review items
- recent cluster activity

Each cluster card must show:

- cluster name
- color
- short summary
- source count
- recent/representative source
- expert status
- last active time

Required actions:

- create cluster
- open cluster
- rename cluster
- accept source suggestion
- move source to suggested cluster

States:

- no vault
- no clusters yet
- clusters with no indexed content
- clusters with expert learning status

### 19. Cluster Detail

Purpose:

- one cluster as a full workspace

Cluster header must show:

- cluster name
- color marker
- short description
- source count
- last active
- expert status
- cluster actions

Required tabs within cluster detail:

- Overview
- Sources
- Chats
- Expert
- Map

#### Overview tab

Must show:

- summary
- cluster health/status
- representative sources
- key activity
- what this cluster is about

#### Sources tab

Must show:

- source list within the cluster
- statuses
- add/move/remove source actions

#### Chats tab

Must show:

- recent chats associated with cluster
- create new cluster-scoped chat

#### Expert tab

Must show:

- expert status
- what the current status means in plain language
- readiness vs learning distinction
- dataset size summary
- last trained time
- whether retraining is needed

Advanced detail area:

- model path
- artifact version
- training log access
- rollback state

Required expert actions:

- train / learn
- retrain
- pause if supported
- activate
- rollback
- delete/reset

#### Map tab

Must show:

- the selected cluster’s local topology
- related sources inside that cluster

### 20. Map

Purpose:

- visual overview of the vault’s context landscape

Must show:

- cluster nodes/blobs
- optional source nodes
- zoom/pan controls
- search/focus control
- filtering tools
- selected-node inspector

Overview node content:

- cluster name
- size by source count or activity
- learning/ready ring state

Selected-node inspector:

- cluster/source title
- summary
- related items
- open actions
- last active

Required interactions:

- pan
- zoom
- hover preview
- select node
- double-click cluster to focus/open
- filter by source type
- filter by expert status
- filter by recency

States:

- empty map
- vault exists but not enough indexed content
- cluster-only overview
- cluster-focused view

### 21. Chat Sessions List

Purpose:

- left-side session management for chat workspace

Must show:

- chat sessions list
- session title
- last updated
- delete action
- new chat action

Required interactions:

- create session
- delete session
- select session

States:

- no vault
- no chats yet

### 22. Chat Workspace

Purpose:

- ask questions across the vault or within a cluster

Layout:

- session list left
- conversation center
- context/status rail right

Composer must support:

- prompt input
- attach files
- context scope selector
- send action
- keyboard shortcuts

Conversation content must support:

- user message
- assistant message
- streaming state
- citations
- retrieval mode/routing explanation
- failure state

Right rail must show:

- active scope
- backend/readiness state
- current attachments
- recent indexed sources
- session metrics or context summary

Required interactions:

- create new chat
- send prompt
- attach/remove files
- switch scope: all vault vs cluster
- open cited source
- regenerate
- save useful answer

States:

- no vault
- backend not ready
- local chat missing
- retrieval only / degraded mode
- streaming response
- interrupted response
- cited answer
- no citation available due degraded mode

### 23. Bridge

Purpose:

- manage external context access

This must feel like a privacy and connection settings area, not a developer console.

Must show:

- Bridge status
- what Bridge does
- allowed vaults/clusters
- approval requests
- approved clients
- connection history / activity
- example usage in expandable advanced blocks

Main sections:

- Overview
- Client approvals
- Approved clients
- Tokens
- Allowed vault scope
- Example setup / advanced configuration

Each approved client should show:

- client name
- claimed identity
- observed identity if available
- executable path if observed
- approval date
- last used
- permission scope

Required actions:

- create approval request
- approve
- reject
- revoke client
- rotate token
- copy token/config
- disable Bridge

States:

- Bridge disabled
- Bridge enabled no clients
- pending approval
- approved clients exist
- blocked due locked vault

### 24. Timeline

Purpose:

- chronological activity across the vault

Must show:

- filter chips by activity type
- search within timeline
- chronological list
- selected item inspector

Activity types:

- source
- cluster
- chat
- bridge
- job/task

Each row should show:

- icon
- title
- detail
- time
- link target

### 25. Tasks

Purpose:

- background work monitor

Must show:

- task filters
- running/queued/failed/completed views
- task list
- selected task details

Task row should show:

- task label
- status
- type
- detail text
- elapsed or completion time

Task detail should show:

- full status
- status detail
- last error
- dedupe key/id if needed in advanced area
- timing

### 26. Activity

Purpose:

- if kept separate from Timeline, use it for richer operational/audit feed

If Activity is redundant with Timeline, designer should recommend merge behavior.

Minimum requirement if retained:

- distinguish system activity from user content history
- show warnings, system notices, approvals, retries, and review-needed items

### 27. Settings

Purpose:

- trusted configuration center for storage, models, privacy, and diagnostics

Required settings sections:

- Profile
- Vault storage
- Local models
- Embeddings / memory search
- OCR
- Diagnostics
- Privacy
- Advanced

#### Profile

Must show:

- display name
- local profile identity
- maybe email if product keeps it

#### Vault storage

Must show:

- active vault path
- data directory
- database path
- storage footprint
- synced-folder safety warning if relevant

Actions:

- open vault folder
- reveal data folder
- export vault
- backup/restore later if in scope

#### Local models

Must show:

- recommended chat model options
- detected local compatible models
- imported local models
- accepted vs rejected status
- active chat model
- active expert model
- pairing guidance

Actions:

- detect installed models
- import model
- validate compatibility
- activate for chat
- activate for expert
- activate approved pair
- download recommended
- cancel download

#### Embeddings / Memory search

Must show:

- current memory-search readiness
- configured path/runtime
- storage location
- test status

Actions:

- choose folder
- configure
- test
- redownload or reconnect

#### OCR

Must show:

- OCR readiness
- available tools
- PDF/image support status
- fallback issues

Actions:

- verify OCR setup
- rerun test

#### Diagnostics

Must show:

- diagnostic export explanation
- redaction explanation
- last export time if tracked
- runtime logs summary

Actions:

- export diagnostics
- copy important paths
- open logs folder

#### Privacy

Must show:

- local-only statement
- Bridge privacy warning
- lock mode
- passphrase/PIN mode explanation
- recovery key state summary

Actions:

- enable strict lock
- set/change PIN
- view recovery key flow

#### Advanced

Must show:

- advanced paths
- developer-ish toggles only if truly needed
- runtime details
- benchmark or indexing backend details only in expandable sections

## Additional Required UI Surfaces

### 28. Dialogs And Utility Flows

Required dialogs:

- Add link
- Paste text
- Confirm delete source
- Confirm delete cluster
- Confirm revoke Bridge client
- Confirm risky `Open anyway` for lock conflict
- File/folder picker flows
- Model import validation result

### 29. Empty States

Design empty states for:

- no vault
- empty vault
- no sources
- no clusters
- no chats
- no tasks
- no timeline items
- no Bridge clients
- no detected models
- no map available

Each empty state should include:

- one sentence explanation
- one primary action
- one optional secondary action

### 30. Error States

Design clear error surfaces for:

- backend offline
- startup failure
- vault locked
- permission denied
- disk full / low disk
- model compatibility rejected
- download failed
- OCR unavailable
- Bridge approval failed
- source extraction failed
- chat runtime unavailable

### 31. Locked / Secured Vault States

If strict lock mode is used, the UI must support:

- locked vault screen
- unlock form
- passphrase re-entry for sensitive actions
- recovery flow entry point
- paused background work message

### 32. Degraded States

Must explicitly distinguish:

- Vault open, chat unavailable
- Vault open, memory search unavailable
- Retrieval-only mode
- Expert not ready but search ready
- Ingestion allowed but OCR unavailable

Never make the UI pretend everything is working when it is degraded.

## Cross-Cutting Interaction Requirements

These interactions should be reflected across the design system:

- drag and drop files/folders
- local file picking
- reveal/open source in OS
- keyboard shortcuts
- copy paths/details
- retry failed operations
- long-running task feedback without fake progress
- hover previews
- inspector patterns
- bulk actions where sensible

## Designer Deliverables Expected From This Brief

The designer should be able to produce:

- full app sitemap
- shell and navigation system
- onboarding flow
- startup/repair/locked/error states
- empty states
- primary tab designs
- cluster detail tab set
- settings IA
- modal/dialog patterns
- status and badge system
- desktop responsive behavior for narrow windows

## Open Product Questions The Design Should Leave Space For

These are unresolved product decisions, so the design should allow either outcome:

- installer path chooser and desktop shortcut option may return
- account/profile step may be simplified or removed
- Activity may merge with Timeline
- full backup/export UI may expand later
- exact approved chat/expert model pairing UI may become more explicit
- dark mode is required later but is not the immediate default reference

## Final Guidance

The designer should assume:

- Windows desktop first
- local-first, privacy-first messaging
- calm and trustworthy tone
- non-technical default path
- power-user detail available in inspectors and advanced sections

The designer should not assume:

- a web/SaaS product
- a mobile-first experience
- cloud-sync or sign-in as the center of the product
- chat as the only core interface
- technical ML controls as first-class user-facing content
