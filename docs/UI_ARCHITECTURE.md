# CML UI Architecture

Last updated: 2026-07-26

## Purpose

This document is the source of truth for CML's user interface architecture. It defines the product feel, visual language, color system, layout rules, navigation model, tab requirements, component contracts, responsive behavior, and interaction states for the desktop app.

Use this document when designing, reviewing, or implementing UI. `docs/UI_PRD.md` explains product requirements; this file explains the concrete interface system that should be built.

The Odin project workspace stays centered on a concise brief and evidence-grounded questions. Graph and tree output appear only after an explicit request rather than as a permanent repository browser.

## Product Feeling

CML should feel like a calm local memory workspace, not a technical AI dashboard.

The user should feel:

- Their personal material is organized into living spaces.
- The app is private, local, and trustworthy.
- Search, chat, clusters, and map are different views of the same memory system.
- Models, embeddings, jobs, and OCR runtime details are hidden behind plain language unless the user opens advanced details.
- The interface is quiet enough for daily use but dense enough for power users.

The desired references are:

- Mindly: approachable spatial organization, gentle hierarchy, simple capture flow.
- Obsidian: graph/map navigation and inspectable local knowledge.
- Apple setup flows: calm first-run setup, one decision per screen, clear storage and privacy.
- Linear/Raycast-level precision: fast keyboard navigation, crisp spacing, subtle state changes.

Avoid:

- Cyberpunk, neon, terminal-first, or heavy purple/blue gradient AI styling.
- Marketing landing pages inside the app.
- Dashboards that expose internal ML machinery as the primary user model.
- Floating-card overload where every section becomes a boxed panel.
- Fake progress bars, fake model readiness, or optimistic copy that hides degraded states.

## Naming And Language

Use user-facing language by default.

| Internal concept | User-facing language | Advanced/details language |
| --- | --- | --- |
| Database | Vault storage | SQLite database |
| Embeddings | Memory search | Embedding model |
| Vector index | Search index | Vector index |
| Model runtime | Local chat | Runtime endpoint |
| MCP/API | Bridge connection | MCP/API |
| Background job | Task | Job |
| Pre-vault mode | Setup mode | `pre_vault` |
| Full-vault mode | Vault open | `full_vault` |

Preferred status labels:

- `Ready`
- `Learning`
- `Needs setup`
- `Needs review`
- `Paused`
- `Issue`
- `Offline`
- `Blocked`

Avoid default-path labels:

- embeddings
- vectors
- schema
- backend
- database
- token
- JSON-RPC

Cluster status language must distinguish:

- `Searchable`
- `Retrieval-only mode`
- `Indexing`
- `Needs update`
- `Paused`
- `Needs attention`

Technical labels are acceptable in Settings, diagnostics, Bridge setup, and expandable detail panels.
User-facing surfaces must not imply that a model memorizes the cluster or acts as factual authority by itself.

## App Shell Architecture

The desktop app uses a persistent shell:

- Left sidebar: primary navigation, vault identity, global search/command access, recent clusters, saved chats.
- Main content area: active tab workspace.
- Optional right panel: contextual inspector for selected cluster, source, map item, job, activity, readiness state, or settings summary.
- Footer/status strip: vault path, backend state, job state, privacy/local indicator, keyboard hints.
- Command palette: global actions, navigation, and source/cluster lookup. Global capture is deferred pending redesign.

### Desktop Window Chrome

Windows builds use app-integrated chrome instead of the native title bar:

- Reserve a 32 px strip at the top of every normal, onboarding, and repair surface.
- The empty strip is draggable; buttons, links, inputs, and menus are non-draggable.
- Keep minimize, maximize/restore, and close controls at the right edge with
  familiar hit targets and accessible labels.
- Keep branding inside the product layout; do not duplicate the Vault logo or page
  title in the chrome.
- Main layouts consume the remaining `h-full` area and do not add another
  viewport-height region below the chrome.
- Window-control IPC operates on the sending window and exposes no arbitrary
  window-management API.

Current routes:

- `/onboarding`
- `/home`
- `/search` as Mind
- `/sources`
- `/clusters`
- `/clusters/$clusterId`
- `/map`
- `/chat`
- `/chat/$chatId`
- `/bridge`
- `/timeline`
- `/tasks`
- `/activity`
- `/settings`

### Left Sidebar

Required regions:

- Vault header: current vault path or `Choose vault`.
- App mark: simple CML/Vault identity, not decorative branding.
- Search button: opens command palette with `Ctrl/Cmd K`.
- Primary nav: Home, Chat, Mind, Sources, Clusters, Map, Timeline, Bridge.
- Utility nav: Tasks, Activity, Settings.
- Recent clusters: up to five, colored dots.
- Saved chats: visible when in Chat route, up to six.
- Profile/storage footer: local profile name and vault path.

Behavior:

- Active route uses a subtle filled/hover state, not a bright pill.
- Sidebar remains fixed on desktop.
- Narrow desktop should collapse or hide labels without losing keyboard access.
- Do not show fake recent clusters or chats. Empty sections should collapse.
- Vault path should be truncated but copyable in future.

### Footer Status Strip

Required indicators:

- Active vault path or `No active vault`.
- Backend state: online/checking/offline/degraded.
- Job state: idle/queued/running/failed count.
- Privacy statement: `All data stays on your device`.
- Shortcut hints: `Ctrl/Cmd K`, `Ctrl/Cmd N`.

Footer should be compact, one line, subdued. It must not become a notification center.

### Command Palette

Required groups:

- Actions: New chat, New cluster, Add link, Add files, Add folder, Paste text, Open vault.
- Go to: Chat, Mind, Sources, Clusters, Map, Bridge, Settings, Tasks.
- Clusters: searchable cluster list with color dot.
- Sources: searchable source list with type icon.
- Future: recent chats, Bridge copy context, diagnostics export.

Behavior:

- `Ctrl/Cmd K` toggles.
- Command names should be verbs.
- No command should silently fail; disabled/unavailable commands need helper text.
- Palette should load backend data only when opened.

## Layout System

### Canvas

The app uses a warm neutral canvas. Pages should feel like a continuous workspace rather than isolated cards.

Primary page layout patterns:

- Two-column workspace: main scroll area + right inspector.
- Three-column workspace: left in-tab list + center detail + right context panel, used for Chat or dense review flows.
- Full-canvas workspace: Map, with overlays and right inspector.
- Setup column: Onboarding, centered and constrained.

### Dimensions

Target desktop:

- Sidebar width: `220px`.
- Right panel width: `320px` to `360px`.
- Main content max readable text width: `760px` to `920px`.
- Dense list rows: `52px` to `76px`.
- Inspector padding: `24px` to `32px`.
- Page padding: `32px` desktop, `20px` narrow, `16px` minimum.
- Onboarding column: `680px`; model comparison maximum `820px`.
- Map canvas height: fills remaining vertical space; minimum useful height `560px`.

Spacing scale:

- `4px`: tiny icon/text gaps.
- `8px`: compact control gaps.
- `12px`: row internal gaps.
- `16px`: card/list item padding.
- `20px`: grouped controls.
- `24px`: section spacing.
- `32px`: page section spacing.
- `48px` to `64px`: hero/primary-workspace separation.

### Surface Hierarchy

Use surfaces intentionally:

- Canvas: main background.
- Sidebar: slightly warmer/lower contrast background.
- Card: repeated objects, list containers, dialogs, inspectors.
- Subtle surface: filters, inactive chips, secondary controls.
- Raised surface: popovers, command palette, modal dialogs.

Do not put every content block inside a card. Prefer:

- Hairline separators for settings groups.
- List rows for repeated content.
- Soft panels for inspectors.
- Cards only for independently selectable objects.

## Visual Style

### Direction

The visual direction is warm, precise, low-noise, and local-first.

Keywords:

- warm graphite
- paper-like neutral
- quiet utility
- spatial memory
- small colored signals
- native desktop
- soft but exact

Not:

- glassmorphism
- bright neon
- dark-only SaaS dashboard
- purple AI gradients
- overly rounded mobile cards
- heavy shadows

### Typography

Current stack: `Inter`, `ui-sans-serif`, `system-ui`, `sans-serif`.

Rules:

- Keep body text direct and readable.
- Do not use viewport-scaled type.
- Do not use negative letter spacing.
- Use medium weight sparingly for labels and titles.
- Prefer small uppercase section labels only in sidebars/inspectors.
- Long-form readable content should use `15px` to `16px` text and comfortable line height.

Type scale:

| Role | Size | Weight | Usage |
| --- | --- | --- | --- |
| App/sidebar title | 14px | 500/600 | Vault identity |
| Page title | 30px to 38px | 500/600 | Top-level tab heading |
| Section title | 16px to 20px | 500/600 | Panel headings |
| Row title | 13px to 15px | 500/600 | Source/cluster/list item title |
| Body | 14px to 15px | 400 | Normal content |
| Metadata | 12px to 13px | 400/500 | Counts, dates, status |
| Microcopy | 11px to 12px | 400/500 | Pills, hints, shortcuts |

### Iconography

Use lucide-style line icons:

- Stroke width around `1.5`.
- Icon sizes: `14px`, `16px`, `18px`, `20px`.
- Icons support labels; they should not replace labels in default desktop width.
- Use icons for type recognition and action clarification, not decoration.

Icon mapping:

- Home/Mind: Home, LayoutGrid/Search.
- Chat: MessageSquare.
- Sources: Layers/Files.
- Clusters: Boxes.
- Map: Globe.
- Bridge: Link2/Cable.
- Tasks: CheckSquare.
- Activity/Timeline: Activity/CalendarDays.
- Settings: Settings.
- Local/private: LockKeyhole/ShieldCheck.
- OCR/image: Image.
- PDF/file: FileText.
- Link: Link2/Globe.

### Motion

Motion should be sparse and meaningful:

- Page step entry: 120ms to 180ms fade/translate, used in onboarding and major empty states.
- Map cluster learning pulse: slow, subtle, only for learning local experts.
- Command palette/dialog entry: standard Radix popover/dialog motion.
- Progress changes: smooth width transition only for real measured progress.

Avoid:

- Decorative looping backgrounds in main workspace.
- Excessive hover motion.
- Bouncy springs for serious data actions.
- Fake loading animations after data has failed.

## Color System

The existing app uses warm neutral hex tokens in `apps/desktop/src/styles.css`. Future new tokens should be semantic and should preferably use OKLCH when expanding the system, but must remain compatible with the current hex aliases.

### Core Light Palette

| Token | Value | Role |
| --- | --- | --- |
| `--bg-canvas` | `#FAFAF8` | Main app background |
| `--bg-sidebar` | `#F5F4F2` | Sidebar background |
| `--bg-card` | `#FFFFFF` | Cards, dialogs, inspectors |
| `--bg-secondary` | `#F0EDE8` | Secondary fills, quiet chips |
| `--bg-hover` | `#EFEFEC` | Hover and active subtle fills |
| `--bg-input` | `#FFFFFF` | Inputs |
| `--border-default` | `#E8E7E3` | Hairlines, panel borders |
| `--border-input` | `#D8D7D2` | Inputs and stronger controls |
| `--border-strong` | `#C8C7C2` | Focus ring, strong separators |
| `--text-primary` | `#1A1916` | Headings, important text |
| `--text-body` | `#3D3C39` | Default body |
| `--text-muted` | `#6B6A66` | Metadata |
| `--text-subtle` | `#9B9A96` | Hints |
| `--text-placeholder` | `#B8B7B2` | Placeholder |
| `--primary` | `#7C6E5A` | Primary action |
| `--primary-hover` | `#9E8C74` | Primary hover |
| `--primary-active` | `#5C5044` | Primary active |
| `--primary-tint` | `#F5F0EB` | Very soft brand fill |

### Recommended OKLCH Expansion

When adding or replacing tokens, use this semantic OKLCH direction:

| Role | OKLCH target |
| --- | --- |
| Canvas | `oklch(0.985 0.005 80)` |
| Sidebar | `oklch(0.965 0.008 80)` |
| Card | `oklch(0.995 0.004 80)` |
| Secondary | `oklch(0.955 0.012 80)` |
| Hover | `oklch(0.94 0.01 80)` |
| Primary text | `oklch(0.22 0.02 60)` |
| Body text | `oklch(0.35 0.015 65)` |
| Muted text | `oklch(0.5 0.015 70)` |
| Primary | `oklch(0.48 0.06 50)` |
| Ring | `oklch(0.55 0.04 60)` |
| Destructive | `oklch(0.58 0.14 25)` |

### Status Colors

Use status colors as small signals: dots, left borders, badges, icons, progress states. Do not flood large surfaces with saturated status fills.

| Status | Foreground | Background | Meaning |
| --- | --- | --- | --- |
| Ready | `--status-ready` `#4A8C5C` | `--status-ready-bg` `#EDF5EA` | Usable, healthy, completed |
| Learning/warning | `--status-warn` `#C88A3A` | `--status-warn-bg` `#FBF2E4` | Running, needs attention soon |
| Issue/error | `--status-error` `#B84040` | `--status-error-bg` `#FAEAEA` | Failed, blocked, destructive |
| Muted/paused | `--status-muted` `#9B9A96` | `--status-muted-bg` `#F0EFEC` | Paused, unknown, inactive |
| Info | `--status-info` `#4A78A8` | `--status-info-bg` `#EAF0FA` | Informational, setup detail |

Status mapping:

- Backend online: Ready.
- Backend checking: Muted with spinner only if actively probing.
- Backend degraded: Warning.
- Backend offline: Issue.
- Job queued/running: Learning/warning.
- Job failed: Issue.
- OCR ready: Ready.
- OCR partial: Warning.
- Embeddings unavailable: Issue or Needs setup.
- Bridge off: Muted.
- Bridge running: Ready.
- Bridge client connected: Info/Ready.
- Project indexing queued/running: Learning/warning.
- Project indexing failed: Issue.

### Cluster Palette

Cluster colors identify spaces, not statuses. Use them consistently across sidebar dots, cluster cards, map blobs, chips, and source assignment UI.

| Cluster color | Token | Value | Character |
| --- | --- | --- | --- |
| Sage | `--cluster-sage` | `#5B8A5B` | grounded, documents, research |
| Terracotta | `--cluster-terracotta` | `#C0704A` | active, writing, creative |
| Sky | `--cluster-sky` | `#4A78A8` | technical, analytical |
| Sand | `--cluster-sand` | `#B8944A` | planning, school/work |
| Lavender | `--cluster-lavender` | `#8A7CC0` | reflective, personal |
| Blush | `--cluster-blush` | `#C06878` | social, emotional, narrative |

Usage rules:

- Use cluster color for dots, thin bars, tiny icon containers, map blobs, and selected outlines.
- Avoid full saturated card backgrounds.
- Use a 10% to 16% tint for icon wells.
- If a cluster has no assigned color, cycle deterministically by cluster ID/index.
- Do not reuse cluster colors as error/warning signals.

### Source Type Palette

Current type badge tokens:

- PDF: soft red.
- Doc/text: soft blue or neutral.
- Note: warm neutral.
- Link: soft green.
- Image: soft blue.
- Audio/video: soft warm neutral.

Required source type badges:

- `PDF`
- `DOC`
- `TXT`
- `MD`
- `LINK`
- `IMG`
- `AUDIO`
- `VIDEO`
- `NOTE`
- `CHAT`

Badges should be compact, readable, and secondary to source titles.

### Dark Mode Direction

Dark mode is required before public V1 but should not become the default visual identity.

Dark mode should be:

- Warm graphite, not pure black.
- Low contrast panels with high contrast text.
- Cluster colors slightly desaturated and lifted for readability.
- Status backgrounds subtle, not neon.
- Borders visible but not bright.

Suggested dark semantic direction:

| Role | Suggested value |
| --- | --- |
| Canvas | `oklch(0.18 0.01 70)` |
| Sidebar | `oklch(0.16 0.01 70)` |
| Card | `oklch(0.22 0.012 70)` |
| Secondary | `oklch(0.27 0.012 70)` |
| Border | `oklch(0.32 0.01 70)` |
| Primary text | `oklch(0.92 0.01 80)` |
| Body text | `oklch(0.82 0.01 80)` |
| Muted text | `oklch(0.66 0.012 80)` |
| Primary | `oklch(0.68 0.055 55)` |

Dark mode must be audited route-by-route. Do not simply invert light tokens.

## Component System

### Buttons

Button variants:

- Primary: one per local action group, solid warm brown.
- Outline: normal secondary action.
- Ghost: quiet list/tool actions.
- Destructive: destructive action only, with confirmation when data loss is involved.
- Icon: toolbar action, requires accessible label.

Rules:

- Primary button copy uses verbs: `Add files`, `Create vault`, `Open Vault`, `Start download`.
- Avoid multiple primary buttons in one panel.
- Dangerous actions must not sit next to primary positive actions without spacing or confirmation.
- Disabled buttons should explain why through adjacent helper text or tooltip.

### Inputs

Input types:

- Search input.
- Command input.
- Text field.
- Textarea.
- Path field.
- URL field.
- Filter select.

Rules:

- Search inputs use leading icon.
- Path fields should show full path and copy/open/reveal actions where appropriate.
- Long text input should avoid card-within-card nesting.
- Validation errors should be inline, not toast-only.

### Cards And Rows

Use cards for:

- Cluster previews.
- Source preview objects.
- Bridge client objects.
- Model choice objects.
- Setup option objects.

Use rows for:

- Source lists.
- Job lists.
- Activity lists.
- Settings groups.
- Chat sessions.

Card contract:

- Title.
- Metadata line.
- One primary signal: color/status/count.
- One action affordance.
- Optional description, max two lines.

Row contract:

- Leading icon/badge.
- Title.
- Metadata and status.
- Optional cluster chip.
- Hover state.
- Selection state.
- Inline secondary actions only on hover/focus for dense lists.

### Chips And Badges

Chip types:

- Cluster chip.
- Source type badge.
- Status badge.
- Permission chip.
- Filter chip.
- Citation chip.

Rules:

- Chips should never be the only carrier of critical information; pair color with text.
- Cluster chips use color dot/swatch plus label.
- Status badges use semantic status color.
- Permission chips in Bridge must be explicit: `Raw snippets allowed`, `Style blocked`, `3 clusters allowed`.

### Tables

Use tables only for dense technical lists:

- Jobs.
- Bridge request history.
- Diagnostics.
- Model integrity/provenance details.

For consumer content, prefer rows/cards over tables.

### Dialogs

Dialog uses:

- Add pasted text.
- Add link.
- Confirm destructive delete.
- Bridge token copy/reveal.
- Advanced diagnostics details.
- Startup repair actions.

Dialog rules:

- Title must state the action.
- Body must state risk if any.
- Primary action bottom right.
- Cancel always available.
- Destructive action requires explicit destructive styling and plain-language consequence.

### Inspector Panels

Right inspector panels should show:

- Selected item identity.
- Status and health.
- Important metadata.
- Suggested next actions.
- Recent related activity.
- Advanced details behind disclosure.

They should not duplicate the full main tab.

## Tab Architecture

## Onboarding

Purpose: get from fresh install to a usable local vault.

Route: `/onboarding`

Required structure:

- Full-window setup canvas.
- Centered step column.
- Step indicator kept subtle.
- One decision per screen.
- Storage/privacy copy visible but not alarmist.
- No sidebar.

Required steps:

1. Welcome: sparse identity, one heading, one setup action.
2. Name: local display name.
3. Library: vault name and folder, exact `.vault` path preview, and disk preflight.
4. Models: destination first, then two or three hardware-and-disk-aware choices,
   existing runtime, or explicit skip.
5. Memory search: explain the embedding model, obtain download consent, support
   an existing cache, and require a real test embedding.
6. Finish: summarize vault, chat-model, memory-search, and storage choices.

Components:

- Setup step container.
- Option card.
- Path picker row.
- Disk preflight status row.
- Model choice card.
- Download progress row.
- Compact non-blocking download notice with terminal fade-out.
- Readiness checklist.
- Startup repair panel.

States:

- Fresh install.
- Pre-vault setup.
- Full-vault restart pending.
- Backend checking.
- Memory search ready.
- Memory search needs setup.
- Local chat skipped.
- Startup repair needed.
- Vault lock conflict.
- Initial model recommendations loading.
- Managed-model download active, installed, cancelled, or failed.
- Managed-model activation verification.

Style:

- Quiet.
- Generous whitespace.
- Minimal icons.
- Hairline separators over boxed wizard chrome.
- No animated marketing hero.
- Polling must not make loading labels blink. The backend model row is
  authoritative for progress and terminal state.

## Home

Purpose: lightweight dashboard that orients the user and gives fast entry into Mind, Chat, recent memories, and clusters.

Route: `/home`

Required components:

- Page header: `Mind` or `Home` depending final naming decision; current UI uses `Mind`.
- Primary ask/search composer.
- Recent memories panel.
- Unsorted sources/inbox panel.
- Suggested clusters strip.
- Right readiness/activity panel.
- Job/readiness summary.

Primary actions:

- Ask/search.
- Add source.
- Review inbox.
- Open cluster.
- Open chat.

Content requirements:

- Show empty vault action when no sources exist.
- Show indexing/running tasks honestly.
- Show memory search availability.
- Show local chat state if not configured.
- Do not show fake source/cluster data.

Visual requirements:

- This is not a marketing hero. The composer is the primary object.
- Suggested clusters should feel spatial and calm.
- Right panel should be a compact summary, not a control wall.

## Mind/Search

Purpose: the primary memory workspace for search, filtering, source review, quick capture, and source-to-cluster routing.

Route: `/search`

Required components:

- Header: `Mind`.
- Quick capture actions: Add note, Add link, Add files, Add folder.
- Search bar with source/tag/summary search.
- Filter chips: All, Unsorted, Recent, Needs review, Failed, type filters.
- Sort control: newest/oldest/relevance.
- Source result grid/list.
- Empty result state.
- Right vault summary panel.
- Cluster summary list.
- Source detail drawer or inspector.

Source card/row requirements:

- Source title.
- Type badge.
- Processing state.
- Cluster chip if assigned.
- Summary/snippet.
- Updated/imported timestamp.
- Source actions: open, reveal, reindex, move, remove.

Required states:

- No vault.
- Empty vault.
- Search no results.
- Embeddings unavailable.
- Index stale.
- Sources need review.
- Link fetch failed.
- OCR partial/failure.

Visual requirements:

- Dense enough for review.
- Strong scanability.
- Avoid huge cards for every source; list mode should be available.
- Use source type badges and cluster chips consistently.

## Sources

Purpose: inspect and manage all imported material.

Route: `/sources`

Required components:

- Header: `Sources`.
- Search input.
- Add files button.
- Paste text button.
- Add link button.
- Add folder button.
- Source list.
- Source detail inspector.
- Add text dialog.
- Add link dialog.
- Import/folder refresh status.

Source list columns/signals:

- Type.
- Title.
- Cluster assignment.
- Processing status.
- Summary/tags.
- Last updated.
- Error indicator if failed.

Source detail inspector:

- Title and type.
- Source path/URL.
- Cluster assignment.
- Processing/indexing status.
- Summary.
- Tags.
- Extracted text preview.
- Page/chunk info where relevant.
- OCR status for images/PDFs.
- Actions: open/reveal, reindex, move to cluster, remove.

Add text dialog:

- Source name.
- Text body.
- Target vault.
- Optional cluster assignment later.

Add link dialog:

- URL.
- Fetch mode status.
- Dynamic fallback availability if needed.

Required states:

- No selected source.
- Source processing.
- Source failed extraction.
- Source deleted/tombstoned.
- Reindex in progress.
- Backend offline/degraded.

## Clusters

Purpose: manage spaces of related context and local expert lifecycle.

Routes: `/clusters`, `/clusters/$clusterId`

Clusters index required components:

- Header: `Clusters`.
- Refresh action.
- New cluster action.
- Cluster cards/list.
- Suggested corrections/review queue.
- Selected cluster inspector.

Cluster card requirements:

- Name.
- Color swatch.
- Description.
- Source count.
- Recent chat count.
- Last active date.
- Local expert status.
- Health/confidence indicator.
- Primary action: open.

Suggested correction row:

- Source title.
- Current assignment.
- Suggested cluster.
- Reason/confidence.
- Accept.
- Dismiss.

Cluster detail required tabs:

- Overview.
- Sources.
- Chats.
- Expert.
- Map.

Overview tab:

- Description.
- Key sources.
- Recent chats.
- Summary/style profile.
- Health and confidence.
- Suggested actions.

Sources tab:

- Source list filtered to cluster.
- Add/move/remove source.
- Needs-review items.
- Source type filters.

Chats tab:

- Saved chats for cluster.
- Recent prompts.
- Start cluster chat.

Map tab:

- Cluster-local source graph.
- Similarity/source spokes.
- Hover previews.
- Correction suggestions.

## Map

Purpose: spatial understanding and navigation of clusters and sources.

Route: `/map`

Required components:

- Header: `Map`.
- Toolbar: Filter, Fit view, List, Back to overview when drilled, Legend.
- Main canvas.
- Cluster blobs.
- Optional source points.
- Hover previews.
- Selected cluster inspector.
- Legend/status panel.

Map overview:

- Cluster blobs without visible lines by default.
- Blob size reflects source count/activity.
- Cluster name below blob.
- Source names hidden until hover/selection.
- Learning expert state can use subtle pulse ring.

Cluster drill-in:

- Center selected cluster.
- Show source nodes around it.
- Show source spokes/similarity lines.
- Back to overview action.
- Source hover preview: title, snippet, type, open/reveal.

Interactions:

- Pan.
- Zoom.
- Drag cluster positions in local session.
- Click cluster to inspect.
- Double-click/open cluster datapoints.
- Search/focus node.
- Keyboard focus for cluster buttons.

Right inspector:

- Cluster name.
- Source count.
- Expert status.
- Description.
- Related sources.
- Actions: open cluster datapoints, suggest correction, archive.

Visual requirements:

- Map should feel like memory geography, not a force-directed debugging graph.
- Lines are secondary and contextual.
- Use cluster color glows carefully.
- Keep text sparse on overview.

## Chat

Purpose: ask the vault, route prompts to relevant context, inspect citations, and save useful answers.

Routes: `/chat`, `/chat/$chatId`

Required layout:

- Left chat session list inside Chat route.
- Center conversation/composer.
- Right context inspector.

Chat index components:

- New chat action.
- Saved/recent chat list.
- Composer.
- Attachment control.
- Cluster override control.
- Suggested prompts.
- Vault context summary.

Conversation detail components:

- Message timeline.
- Streaming response area.
- Citation chips.
- Used cluster indicator.
- Source snippets.
- Attachment preview.
- Save answer.
- Useful/not useful feedback.
- Regenerate.
- Retry failed generation.
- Add answer to cluster memory.

Composer requirements:

- Placeholder: `Ask across your vault...` or scoped cluster wording.
- `Ctrl/Cmd Enter` sends.
- Attachment button.
- Cluster/source scope selector.
- Runtime/degraded state visible before send.

Routing indicator examples:

- `Using Research Notes because your question asks about its sources.`
- `Using Writing Style for tone and Assignment Sources for facts.`
- `No local chat model connected. Showing context-only answer.`

Right inspector:

- Active vault.
- Selected clusters.
- Sources likely to be used.
- Runtime status.
- Memory search status.
- Coverage/analysis state.
- Recent citations.

Required states:

- No vault.
- No sources.
- Embeddings unavailable.
- Local chat unavailable.
- Runtime crashed.
- Generation interrupted/retriable.
- Citation deleted/stale.
- Complete analysis unavailable: show `Expanded analysis is available; complete analysis is not ready yet.`

## Bridge

Purpose: let external local tools request selected context while making privacy boundaries explicit.

Route: `/bridge`

Required components:

- Header: `Bridge`.
- Plain-language explanation.
- Bridge status card.
- Surface cards: MCP, CLI, Copy context.
- Permission panel.
- Bridge clients list.
- Token create/reveal/copy flow.
- Per-client permission controls.
- Recent context requests.
- Test bridge action.

Bridge status labels:

- Off.
- Running.
- Client connected.
- Needs setup.
- Issue.

Permission controls:

- Allowed vaults.
- Allowed clusters.
- Raw source snippets allowed/blocked.
- Style profile allowed/blocked.
- Expert calls allowed/blocked.
- Capture/logging permissions.
- Revoke client.
- Rotate token.

Client row requirements:

- Client name/type.
- Created/last used.
- Enabled state.
- Permission summary.
- Copy token/config.
- Rotate/revoke.

Recent request row:

- Time.
- Client.
- Vault/cluster scope.
- Allowed/denied.
- Raw snippets served yes/no.
- Error code if denied.

Copy:

- `Bridge lets another local app ask your vault for relevant context.`
- `Only enabled clients with a token can connect.`
- `A connected AI app may send received context to its own provider.`

Visual requirements:

- Privacy boundaries must be visually prominent.
- Token values must be hidden by default.
- Dangerous permission expansion requires clear copy.

## Timeline

Purpose: chronological memory and app activity view.

Route: `/timeline`

Required components:

- Header: `Timeline`.
- Search activity input.
- Activity list grouped by date.
- Filters by type: sources, chats, clusters, Bridge, jobs.
- Right activity detail inspector.

Activity row:

- Icon/type.
- Title.
- Time.
- Related source/cluster/chat.
- Status.

Detail panel:

- Event summary.
- Related objects.
- Source/cluster links.
- Diagnostic detail for technical events.

Required states:

- Empty timeline.
- Filter no results.
- Backend offline.

## Tasks

Purpose: visible background work and failures.

Route: `/tasks`

Required components:

- Header: `Tasks`.
- Run once/manual process action for dev/admin.
- Search jobs.
- Status filters.
- Job table/list.
- Job detail inspector.

Job row:

- Type.
- Status.
- Created time.
- Attempts.
- Scope/vault/source.
- Next retry.
- User-visible label.

Job detail inspector:

- Job ID.
- Type.
- Status.
- Status detail.
- Payload summary with sensitive fields redacted.
- Attempts/max attempts.
- Timestamps.
- Actions: refresh, cancel if cancellable, retry where allowed.

Status language:

- `Waiting`
- `Running`
- `Done`
- `Will retry`
- `Failed`
- `Blocked`
- `Needs review`

Never show raw internal payload as the primary UI. Advanced disclosure is acceptable.

## Activity

Purpose: recent system-level events and user-visible status.

Route: `/activity`

Required components:

- Summary cards.
- Recent event list.
- Failure/warning list.
- Filters by subsystem.
- Detail inspector.

Use Activity for user-visible audit and status; use Tasks for job execution details.

Events should include:

- Source imported.
- Source failed.
- Cluster changed.
- Expert status changed.
- Bridge request served/denied.
- Vault lock override.
- Diagnostics exported.
- Model/embedding setup changed.

## Settings

Purpose: configure local runtime, storage, imports, privacy, diagnostics, and advanced setup.

Route: `/settings`

Required structure:

- Left in-tab settings section nav.
- Main settings content.
- Right device readiness panel.

Settings sections:

- Profile.
- Vault/storage.
- Local chat.
- Memory search.
- Models and provenance.
- OCR.
- Local imports.
- Bridge/security.
- Evidence retention.
- Diagnostics.
- Advanced.

Current and required cards:

- Synthesis runtime.
- Chat model.
- Embedding model.
- OCR.
- Disk usage.
- Evidence retention.
- Local imports.
- Diagnostics.
- Device readiness.

Model provenance UI:

- Model ID.
- Display name.
- Source repo.
- Filename.
- Expected SHA-256.
- Actual SHA-256 if installed.
- Integrity state.
- Size.
- Commit/revision.
- Download status.
- Warning if unverified.

Memory search UI:

- Provider.
- Cache path.
- Available/unavailable state.
- Test result.
- Download recommended embedding model.
- Cancel download.
- Hash/dev fallback hidden or clearly marked development-only.

OCR UI:

- Image OCR available.
- PDF OCR available.
- Engine.
- Tesseract path.
- Ghostscript path.
- qpdf path.
- Missing components.
- Packaged/local distinction.

Local imports UI:

- Imported folder path.
- Watched on/off.
- Last refresh.
- Counts: imported, updated, moved, missing, failed.
- Refresh now.
- Tombstone missing option.

Evidence retention UI:

- Snapshot retention age.
- Max items.
- Max payload.
- Compact now.
- Prune stored query evidence.
- Explanation of privacy/storage tradeoff.

Diagnostics UI:

- Export diagnostics.
- Startup repair summary.
- Log rotation status.
- Redaction guarantee.
- Copy support bundle path.

Device readiness panel:

- Vault path.
- Backend mode.
- Backend identity/auth state.
- Memory search.
- Local chat.
- OCR.
- Disk space.
- Bridge.
- Jobs.

## Cluster Detail Route

Purpose: deep single-cluster workspace.

Route: `/clusters/$clusterId`

Required detail architecture:

- Header with cluster name, color, status, source count.
- Main tabs: Overview, Sources, Chats, Expert, Map.
- Right inspector or action rail.
- Breadcrumb/back to Clusters.

Actions:

- Rename.
- Edit description.
- Start cluster chat.
- Add sources.
- Move sources.
- Merge.
- Split.
- Retrain local expert.
- Roll back expert.
- Export.
- Delete/archive with confirmation.

## Chat Detail Route

Purpose: persisted conversation with retrieval state and actions.

Route: `/chat/$chatId`

Required detail architecture:

- Conversation header: title, scope, saved state.
- Messages.
- Retrieval context panel.
- Citation/source inspector.
- Composer.
- Actions: save, rename, delete, regenerate, retry, export.

Message requirements:

- User message.
- Assistant message.
- Context-only/degraded note if applicable.
- Citation chips inline or below answer.
- Tool/status messages only when user-relevant.
- Failed generation retry affordance.

## Cross-Cutting States

### Empty States

Empty state pattern:

- Short title.
- One plain-language sentence.
- One primary action.
- Optional secondary action.
- Small icon/illustration only if helpful.

Examples:

- No vault: `Choose a place for your local memory.`
- Empty vault: `Drop files, links, screenshots, or notes to begin.`
- No clusters: `Add a few items and Vault will suggest spaces.`
- No chat: `Ask your vault anything.`
- Bridge off: `Turn on Bridge when you want another local AI app to use your memory.`

### Loading States

Rules:

- Use skeletons for lists.
- Use spinners only for actions already started by the user or short polling states.
- Use real progress when backend reports bytes/counts.
- No fake progress bars.
- If loading exceeds 5 seconds, show what is being checked.

### Error States

Error pattern:

- What happened.
- Why it likely happened.
- Whether data is safe.
- Next action.
- Optional details disclosure.

Required visible errors:

- Backend offline/degraded.
- Vault path unavailable.
- Vault lock conflict.
- Disk space low.
- File extraction failed.
- OCR failed.
- Link fetch blocked/failed.
- Indexing failed.
- Embedding setup unavailable.
- Local chat model unavailable.
- Project indexing failed.
- Bridge denied request.
- Startup repair needed.

### Degraded Mode

Degraded mode must be explicit:

- If memory search unavailable: search/chat should say memory search needs setup.
- If local chat unavailable: chat can show context-only answers, but must label them.
- If OCR unavailable: images/scanned PDFs can be stored but text extraction is limited.
- If Bridge off: external tools cannot access context.
- If backend auth degraded: private API routes should not be treated as online.

## Accessibility

Requirements:

- All icon-only buttons have `aria-label`.
- Keyboard navigation for sidebar, command palette, dialogs, tabs, map cluster buttons.
- Visible focus rings using `--ring`.
- Color is never the only status signal.
- Text contrast meets WCAG AA.
- Motion respects reduced-motion preference.
- Dialogs trap focus and restore focus.
- Toasts are not the only place errors appear.
- Map interactions have list/detail fallback.

## Responsive Desktop Behavior

Public V1 does not require dedicated mobile UI, but narrow desktop windows must work.

Breakpoints:

- Wide desktop: sidebar + main + right panel.
- Medium desktop: sidebar + main, right panel can collapse/drawer.
- Narrow desktop: collapsible sidebar, single-column content, inspectors below or drawer.

Rules:

- No horizontal scrolling for primary workflows.
- Critical actions remain visible at `1024px` width.
- Footer can hide shortcut hints first.
- Right inspectors should collapse before main content becomes unusable.
- Map toolbar can wrap into two rows.
- Chat session list can collapse into a drawer.

## Data And Privacy UI Rules

Every tab must respect local-first boundaries:

- Do not imply cloud sync unless user explicitly chose synced folders or external tools.
- Show exact vault paths in Settings and onboarding.
- Bridge UI must explain that external apps may transmit received context.
- Diagnostics UI must state redaction behavior.
- Deletion UI must distinguish record deletion, source file deletion, and index cleanup.
- Tokens are never shown by default.
- User content should not appear in logs/diagnostic summaries unless explicitly requested.

## Implementation Guardrails

Follow these rules when editing UI:

- Preserve the warm neutral visual system.
- Use semantic tokens instead of raw one-off colors when possible.
- Keep new UI copy plain and non-technical.
- Avoid new mock fallback data in production surfaces.
- Add empty/error/loading states at the same time as happy path UI.
- Do not introduce a purple/blue AI-gradient default.
- Do not make Chat the first screen after onboarding.
- Do not call content indexed, searchable, or ready unless a real backend state supports the claim.
- Keep Bridge permissions and privacy visible.
- Keep backend degraded/auth states explicit.
- Add route-level QA notes when a tab gains new setup, diagnostic, or destructive behavior.

## UI Workflow Architecture

This section defines how the app should behave as a connected product, not only as separate tabs. Every workflow must keep the user oriented: what object they are acting on, what state it is in, what will happen after the action, and whether data stays local.

### Global Navigation Workflow

Entry points:

- Fresh install opens `/onboarding`.
- Existing usable vault opens the main shell at `/home` or `/search`, depending on the last active route.
- Deep links to `/clusters/$clusterId` or `/chat/$chatId` should load the shell, then fetch the object. Missing objects show a clear not-found state with a back action.

Navigation interactions:

- Sidebar nav switches primary workspaces without opening a modal.
- Command palette can create a chat, jump to routes, open a cluster, or find a source.
- Recent cluster links open cluster detail.
- Saved chat links open persisted chat detail.
- Back links return to the parent list, not browser history if the parent is semantically clear.
- Right inspectors should update when selection changes and should not clear the main tab context.

Required route transitions:

- Home quick actions can route to Chat, Sources, Clusters, Map, Bridge, Settings.
- Mind/Search source selection opens source inspector or routes to Sources when full editing is needed.
- Cluster card `Open` routes to `/clusters/$clusterId`.
- Cluster detail `Chat with cluster` creates a scoped chat and routes to `/chat/$chatId`.
- Citation/source chips in Chat route to Sources or open a source inspector.
- Bridge client setup stays inside Bridge; it should not navigate to Settings unless advanced security settings are required.
- Settings readiness cards route to the exact section needing setup, not a generic settings page.

Navigation failure rules:

- Backend unavailable: show degraded state in the current tab, keep sidebar usable.
- Object missing: show not-found with one primary route back to parent list.
- Auth degraded: show private API unavailable copy; do not silently fall back to mock data.
- Vault not selected: redirect to onboarding or show a local vault setup card, depending on route.

### First-Run And Vault Setup Workflow

Goal: move from no vault to a usable local memory workspace.

Steps and interactions:

1. Welcome screen explains local-first behavior and asks the user to continue.
2. Profile/name step captures a local display name only.
3. Vault naming step asks for the vault name.
4. Vault location step opens a folder picker, previews the exact `.vault` path, runs disk preflight, and blocks continue if the location is invalid.
5. Memory search step selects or installs the embedding model. It must show size, cache path, and setup status.
6. Local chat step lets the user connect an existing runtime, download a recommended model, or continue in context-only mode.
7. OCR readiness step reports packaged OCR availability and explains limitations if partial.
8. Summary step lists vault path, memory search, local chat, OCR, and unresolved setup.

Button behavior:

- `Continue` advances only after required fields are valid.
- `Choose folder` opens native folder picker and does not mutate state until the user confirms.
- `Start download` begins a measured download with bytes/progress/ETA when available.
- `Cancel download` cancels the active download and preserves previous usable model state.
- `Set up later` is allowed for local chat but not for production memory search unless the app clearly enters degraded mode.
- `Open vault` restarts or switches backend into full-vault mode and then routes to the main shell.

Failure states:

- Vault lock conflict shows owner/process details and safe choices.
- Disk preflight failure explains required and available space.
- Embedding setup failure keeps vault creation possible only if the app is explicitly in degraded setup.
- Backend restart failure shows copyable diagnostic detail.

### Capture And Ingestion Workflow

Goal: add material to the vault and make processing state visible.

Entry points:

- Mind quick actions: Add note, Add link, Add files, Add folder.
- Sources header buttons.
- Chat attachment button.
- Bridge/extension capture tools.
- Local folder import settings.

Interactions:

- `Add files` opens a native file picker, creates source records, queues extraction/indexing, and shows imported/failed counts.
- `Add folder` opens a folder picker, scans supported files, records an import when a vault is selected, and can later refresh/tombstone missing files.
- `Add note` or `Paste text` opens a dialog with title/body fields and optional cluster assignment.
- `Add link` opens a URL dialog, fetches static readable text first, then dynamic browser extraction if the static page is too thin and the runtime is available.
- Chat attachments create source records tied to the chat and optional cluster scope before generation.
- Source rows update through states: created, extracting, indexed, failed, deleted/tombstoned.

Required feedback:

- Immediate optimistic source row may appear only after backend record creation succeeds.
- Long extraction/indexing shows task state, not fake completion.
- Partial OCR is visible on the source inspector.
- Failed ingestion shows the file/link, reason, and retry/reveal/remove actions.

Data safety:

- Removing a source must explain whether CML removes only the vault record/indexed text or touches the original file.
- Tombstoned folder files should disappear from search immediately while cleanup runs.

### Search, Review, And Organization Workflow

Goal: help users find memories and correct organization.

Interactions:

- Search input updates result list after debounce or explicit submit.
- Filter chips constrain by state/type/cluster/review status.
- Sort control changes ordering without resetting selection.
- Source selection opens inspector and preserves list scroll.
- Cluster chip opens cluster detail or filters by cluster depending on local context.
- Suggested correction rows allow `Accept` and `Dismiss`.
- Accepting a cluster suggestion moves the source, refreshes affected cluster profiles, and updates counts.
- Dismissing a suggestion records the decision and removes the item from the visible queue.

Required states:

- Empty vault: suggest add files/link/note.
- No results: show active query/filter and a clear reset action.
- Memory search unavailable: show setup path and block semantic claims.
- Index stale: show reindex action and affected count when available.

### Chat And Context Workflow

Goal: answer using vault context with visible routing, citations, and degraded states.

Interactions:

- `New chat` creates a persisted session when a vault exists; otherwise routes to chat index with setup prompt.
- Composer sends on button click or `Ctrl/Cmd Enter`.
- Attachment button opens file picker and shows pending attachments before send.
- Cluster scope selector changes routing from global vault to selected cluster.
- On send, UI creates a user message, starts retrieval/context build, then streams or displays the answer.
- Stop button cancels the active stream without deleting messages.
- Retry/regenerate uses the last user prompt and preserves citation history.
- Citation chips open source context and preserve chat scroll.
- Save/useful/not useful actions update message metadata.

Required answer states:

- Local chat ready: stream generated answer with citations.
- Local chat unavailable: show context-only answer and label it.
- Memory search unavailable: block retrieval-backed claims and guide setup.
- Runtime interrupted: show retriable placeholder.
- Source deleted/stale: citation chip shows stale/deleted state.
- Complete analysis unavailable: explain that expanded analysis exists but complete analysis is not ready.

### Bridge Workflow

Goal: let external local clients use selected context with explicit privacy boundaries.

Interactions:

- Bridge enable/disable toggle changes whether clients can connect.
- Permission toggles update allowed vaults, clusters, raw snippets, style profiles, and expert calls.
- `Add client` creates a client token and shows it once.
- `Copy token` copies hidden token after explicit action.
- `Rotate token` invalidates the old token.
- `Revoke` disables the client after confirmation.
- Recent requests show allowed/denied state and reason.
- Copy context buttons generate MCP/CLI/local HTTP examples.

Privacy rules:

- Token values hidden by default.
- UI must state that external AI apps may send received context to their provider.
- Denied requests are visible in history.
- Permission expansion uses direct copy, not vague toggles.

### Tasks And Activity Workflow

Goal: make background work and system events understandable.

Task interactions:

- `Run once` processes queued backend jobs in development/admin context.
- Status filters show queued/running/done/failed/blocked/cancelled/manual review.
- Selecting a job opens detail inspector.
- `Cancel job` is enabled only when the job is cancellable.
- Refresh reloads queue status without losing current selection.

Activity interactions:

- Timeline/Activity filters group by type and date.
- Selecting an event opens related detail.
- Related links route to source/cluster/chat/Bridge detail.

Copy rules:

- Use `Task` for user-visible work.
- Use `Job ID`, payload, and failure code only in advanced detail.
- Failed tasks explain user impact and next action.

### Settings And Readiness Workflow

Goal: configure local dependencies and expose device readiness.

Interactions:

- Settings section nav switches panels without leaving route.
- Runtime cards support configure/test/copy path/open path where applicable.
- Model download cards require a validated destination and support
  recommendation/start/cancel/status/integrity display. Terminal state replaces
  stale progress and the compact notice fades out.
- Embedding setup supports provider/cache path/test/download/cancel.
- OCR card reports packaged paths and missing components.
- Local imports support refresh now, watched on/off, tombstone missing, and failure review.
- Diagnostics supports export and copy support bundle path.
- Evidence retention supports compact/prune actions with storage/privacy explanation.

Readiness panel:

- Shows Vault path, backend mode/auth, memory search, local chat, OCR, disk, Bridge, jobs.
- Each failed item routes to exact setup section.
- It should not use green checks for skipped/degraded states.

## Titles And Button Inventory

This inventory defines preferred visible titles and button copy. Existing implementation should converge toward these labels unless a route-specific reason exists.

### Global Shell

Titles:

- App identity: `CML` or current vault name.
- Sidebar groups: `Recent clusters`, `Saved chats`.
- Footer labels: `Local`, `Backend`, `Tasks`, `Vault`.

Buttons and interactions:

| Control | Location | Action |
| --- | --- | --- |
| Search / command button | Sidebar | Opens command palette. |
| New chat plus button | Saved chats group | Creates a new chat or routes to Chat. |
| Sidebar nav item | Sidebar | Navigates to route and marks active state. |
| Recent cluster row | Sidebar | Opens cluster detail. |
| Saved chat row | Sidebar | Opens chat detail. |

### Command Palette

Titles:

- Dialog title: `Command`.
- Groups: `Actions`, `Go to`, `Clusters`, `Sources`.

Commands:

| Command | Action |
| --- | --- |
| `New chat` | Creates/renders new chat flow. |
| `New cluster` | Routes to Clusters and focuses creation flow when implemented. |
| `Add source` | Routes to Sources. |
| `Go to Chat` | Routes to Chat. |
| `Go to Clusters` | Routes to Clusters. |
| `Go to Sources` | Routes to Sources. |
| `Go to Map` | Routes to Map. |
| `Go to Bridge` | Routes to Bridge. |
| `Go to Settings` | Routes to Settings. |

### Onboarding

Titles:

- `Welcome to CML`
- `Create your local profile`
- `Name your vault`
- `Choose vault location`
- `Set up memory search`
- `Set up local chat`
- `Check local OCR`
- `Ready to open your vault`

Buttons:

| Button | Action |
| --- | --- |
| `Continue` | Advances step after validation. |
| `Back` | Returns to previous step. |
| `Choose folder` | Opens native folder picker. |
| `Use recommended model` | Selects default model path/download plan. |
| `Connect existing runtime` | Opens runtime URL/model fields. |
| `Set up later` | Enters explicit degraded mode where allowed. |
| `Start download` | Starts model/embedding download. |
| `Cancel download` | Cancels active download. |
| `Open vault` | Enters full vault mode. |

### Home

Titles:

- Page title: `Home`.
- Sections: `Ask your vault`, `Recent memories`, `Recent clusters`, `Device readiness`, `Local status`.

Buttons:

| Button | Action |
| --- | --- |
| `Ask` | Starts chat from composer. |
| `Add source` | Routes to Sources or opens capture menu. |
| `Open Mind` | Routes to Mind/Search. |
| `New chat` | Creates chat. |
| `Review setup` | Routes to Settings readiness section. |

### Mind/Search

Titles:

- Page title: `Mind`.
- Sections: `Quick capture`, `Memory results`, `Vault summary`, `Clusters`.

Buttons:

| Button | Action |
| --- | --- |
| `Add note` | Opens text capture dialog. |
| `Add link` | Opens link dialog. |
| `Add files` | Opens file picker. |
| `Add folder` | Opens folder picker/import scan. |
| `Reset filters` | Clears active query/filter state. |
| `Open source` | Opens inspector or source detail. |
| `Move` | Opens cluster assignment. |
| `Remove` | Starts delete confirmation. |

### Sources

Titles:

- Page title: `Sources`.
- Dialog titles: `Add text source`, `Add link`.
- Inspector title: selected source title.
- Sections: `All sources`, `Source detail`, `Actions`, `Extraction`, `Memory search`.

Buttons:

| Button | Action |
| --- | --- |
| `Add files` | Opens file picker and imports selected files. |
| `Paste text` | Opens text-source dialog. |
| `Add link` | Opens link-source dialog. |
| `Add folder` | Opens folder picker/import scan. |
| `Cancel` | Closes dialog without saving. |
| `Save text` | Creates text source. |
| `Save link` | Creates link source. |
| `Reveal in folder` | Opens local file location when available. |
| `Open source` | Opens URL or local file. |
| `Reindex` | Queues source reindex. |
| `Remove source` | Starts safe delete/tombstone flow. |
| `Prev` / `Next` | Paginates source list. |

### Clusters Index

Titles:

- Page title: `Clusters`.
- Sections: `Cluster spaces`, `Suggested corrections`, `Cluster detail`.

Buttons:

| Button | Action |
| --- | --- |
| `Refresh` | Reloads clusters/suggestions. |
| `New cluster` | Opens create cluster flow. |
| `Open` | Routes to cluster detail. |
| `Accept` | Applies suggested source move. |
| `Dismiss` | Hides suggested correction. |
| `Merge` | Starts cluster merge flow when implemented. |

### Cluster Detail

Titles:

- Page title: cluster name.
- Back link: `Back to clusters`.
- Tabs: `Overview`, `Sources`, `Chats`, `Memory profile`, `Map`.
- Sections: `Summary`, `Top memories`, `Recent sources`, `Recent chats`, `Search status`, and recent tasks.

Buttons:

| Button | Action |
| --- | --- |
| `Chat with cluster` | Creates scoped chat and routes to it. |
| `Add source` | Opens source add/move flow for this cluster. |
| `More cluster actions` | Opens action menu when implemented. |
| `View all memories` | Routes to Sources/Mind filtered to cluster. |
| `View all sources` | Routes to Sources filtered to cluster. |
| `View all chats` | Routes to Chat list. |
| `View profile` | Opens Memory profile tab. |

### Map

Titles:

- Page title: `Map`.
- Toolbar/sections: `Legend`, `Cluster view`, `Data points`, `Selected source`, `Selected cluster`.

Buttons:

| Button | Action |
| --- | --- |
| `Fit view` | Resets pan/zoom to useful bounds. |
| `List` | Opens list fallback or side list. |
| `Back to overview` | Leaves cluster drill-in. |
| `Zoom in` | Increases canvas zoom. |
| `Zoom out` | Decreases canvas zoom. |
| `Reset zoom` | Restores default zoom. |
| Cluster blob button | Selects/opens cluster. |
| Source node button | Selects source preview. |
| `Open file` | Opens selected local source. |
| `Open location` | Reveals file or opens URL. |

### Chat

Titles:

- Page title: `Chat`.
- Detail title: chat title, editable.
- Sections: `Recent chats`, `Saved chats`, `Context`, `Citations`, `Attachments`, `Runtime`.

Buttons:

| Button | Action |
| --- | --- |
| `New chat` | Creates a new chat session. |
| `Send` | Sends composer prompt. |
| `Attach files` | Opens file picker for prompt-zero attachments. |
| `Stop` | Stops active stream/generation. |
| `Retry` | Retries failed or interrupted generation. |
| `Regenerate` | Regenerates answer from same prompt/context. |
| `Save` / `Saved` | Toggles saved state for chat/message. |
| `Useful` | Marks answer useful. |
| `Not useful` | Marks answer not useful. |
| `Open sources` | Routes to Sources/citation detail. |
| `Remove attachment` | Removes pending attachment before send. |
| `Back to chats` | Returns to chat index. |

### Bridge

Titles:

- Page title: `Bridge`.
- Cards: `MCP`, `CLI`, `Copy context`.
- Sections: `Permissions`, `Clients`, `Recent requests`, `Setup examples`.

Buttons:

| Button | Action |
| --- | --- |
| `Refresh` | Reloads Bridge status/permissions. |
| `Add client` | Creates tokenized Bridge client. |
| `Copy token` | Copies visible one-time token. |
| `Rotate` | Rotates client token. |
| `Delete` / `Revoke` | Disables client after confirmation. |
| `Copy MCP config` | Copies MCP setup snippet. |
| `Copy CLI example` | Copies CLI command. |
| `Copy HTTP example` | Copies local HTTP request. |
| `Copy bridge token` | Copies current Bridge token after explicit action. |
| Permission toggles | Update raw/style/expert access. |

### Timeline

Titles:

- Page title: `Timeline`.
- Sections: `Activity detail`, date group labels.

Buttons:

| Button | Action |
| --- | --- |
| Filter chip | Changes visible activity type. |
| Activity row | Selects detail. |
| `Open related item` | Routes to source/cluster/chat/detail where available. |

### Tasks

Titles:

- Page title: `Tasks`.
- Sections: `Job detail`, `Queue`, `Running`, `Failed`, `Needs review`.

Buttons:

| Button | Action |
| --- | --- |
| `Run once` | Processes due jobs once. |
| Status filter | Filters task list. |
| Job row | Selects job detail. |
| `Refresh` | Reloads queue state. |
| `Cancel job` | Cancels selected cancellable job. |

### Activity

Titles:

- Page title: `Activity`.
- Sections: `System status`, `Recent events`, `Warnings`, `Failures`.

Buttons:

| Button | Action |
| --- | --- |
| Event filter | Filters by subsystem/type. |
| Event row | Opens event detail. |
| `Open related item` | Routes to source/cluster/chat/settings. |

### Settings

Titles:

- Page title: `Settings`.
- Sections: `Profile`, `Vault storage`, `Local chat`, `Memory search`, `Models and provenance`, `OCR`, `Local imports`, `Bridge and security`, `Evidence retention`, `Diagnostics`, `Advanced`.
- Right panel: `Device readiness`.

Buttons:

| Button | Action |
| --- | --- |
| Section nav item | Switches settings section. |
| `Choose folder` | Opens path picker. |
| `Test runtime` | Probes local chat runtime. |
| `Start download` | Starts model/embedding download. |
| `Cancel download` | Cancels active download. |
| `Configure` | Saves provider/runtime settings. |
| `Refresh now` | Runs watched-folder refresh. |
| `Compact now` | Compacts evidence/snapshots. |
| `Prune query cache` | Removes stale/oversized query evidence. |
| `Export diagnostics` | Writes diagnostic bundle. |
| `Create backup` | Creates SQLite/vault safety backup. |
| `Copy path` | Copies file/folder/bundle path. |

### Error And Not-Found Surfaces

Titles:

- `Page not found`
- `Cluster not found`
- `Chat not found`
- `Backend unavailable`
- `Setup needed`
- `Vault locked`
- `Something needs review`

Buttons:

| Button | Action |
| --- | --- |
| `Back to home` | Routes to Home. |
| `Back to clusters` | Routes to Clusters. |
| `Back to chats` | Routes to Chat. |
| `Retry` | Repeats failed load/action. |
| `Copy details` | Copies diagnostic-safe error text. |
| `Open settings` | Routes to relevant setup section. |

## Route Acceptance Checklist

Each route should pass this checklist:

- It has a clear purpose in one sentence.
- It has an empty state.
- It has a loading state.
- It has a backend unavailable/degraded state.
- It has visible primary action.
- It has clear status language.
- It does not expose internal technical language by default.
- It supports keyboard navigation.
- It has no fake data in production state.
- It uses current tokens and spacing.
- It works at wide and narrow desktop widths.
- It does not hide privacy/security consequences.

## Public V1 UI Completion Gates

The UI is public-V1 ready only when:

- Onboarding creates/opens a vault with exact local storage path and honest readiness states.
- User lands on Mind/Home, not Chat or a marketing page.
- Sources can be added, inspected, reindexed, moved, and removed with clear status.
- Clusters can be reviewed, renamed, corrected, opened, and inspected.
- Chat shows cluster/source routing and citations clearly.
- Map is navigable and supports cluster/source inspection.
- Bridge permissions, tokens, request history, and privacy boundaries are understandable.
- Settings shows model provenance, memory search, local chat, OCR, storage, diagnostics, and evidence retention.
- Tasks and Activity make background work and failures visible.
- Empty, loading, degraded, and failure states are complete.
- Dark mode and narrow desktop QA pass.
- Clean packaged Windows visual QA passes.
- No UI claims a model learned or indexed content unless a real backend state supports that claim.
