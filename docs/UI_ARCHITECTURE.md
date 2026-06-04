# CML UI Architecture

Last updated: 2026-06-04

## Purpose

This document is the source of truth for CML's user interface architecture. It defines the product feel, visual language, color system, layout rules, navigation model, tab requirements, component contracts, responsive behavior, and interaction states for the desktop app.

Use this document when designing, reviewing, or implementing UI. `docs/UI_PRD.md` explains product requirements; this file explains the concrete interface system that should be built.

## Product Feeling

CML should feel like a calm local memory workspace, not a technical AI dashboard.

The user should feel:

- Their personal material is organized into living spaces.
- The app is private, local, and trustworthy.
- Search, chat, clusters, and map are different views of the same memory system.
- Models, embeddings, jobs, OCR, and LoRA are hidden behind plain language unless the user opens advanced details.
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
| LoRA adapter | Local expert | Adapter |
| Fine-tuning | Learning | Training |
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
- LoRA
- fine-tune
- database
- token
- JSON-RPC

Technical labels are acceptable in Settings, diagnostics, Bridge setup, and expandable detail panels.

## App Shell Architecture

The desktop app uses a persistent shell:

- Left sidebar: primary navigation, vault identity, global search/command access, recent clusters, saved chats.
- Main content area: active tab workspace.
- Optional right panel: contextual inspector for selected cluster, source, map item, job, activity, readiness state, or settings summary.
- Footer/status strip: vault path, backend state, job state, privacy/local indicator, keyboard hints.
- Command palette: global actions, navigation, source/cluster lookup, future quick capture.

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
- Expert retrieval-ready: Ready with neutral text; do not imply trained adapter.
- Expert training-running: Learning.
- Expert training-failed: Issue.
- Expert rollback-ready: Warning/info.

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

1. Welcome/sign-in truthfulness: local profile is enough; do not imply cloud account unless real auth exists.
2. Name/local profile.
3. Vault name.
4. Vault location: folder picker, exact `.vault` path preview, disk preflight.
5. Local chat setup: recommended model, existing runtime, set up later.
6. Memory search setup: required real embedding setup, download/link existing cache, test embedding.
7. Ready summary: vault path, memory search, local chat, OCR, imported items, unresolved setup.

Components:

- Setup step container.
- Option card.
- Path picker row.
- Disk preflight status row.
- Model choice card.
- Download progress row.
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

Style:

- Quiet.
- Generous whitespace.
- Minimal icons.
- Hairline separators over boxed wizard chrome.
- No animated marketing hero.

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

Expert tab:

- User-facing expert status.
- Retrieval-backed availability.
- Learning/training state.
- Metrics if available.
- Dataset count.
- Last trained.
- Active adapter version.
- Rollback state.
- Retrain action.
- Advanced logs behind disclosure.

Map tab:

- Cluster-local source graph.
- Similarity/source spokes.
- Hover previews.
- Correction suggestions.

Copy rules:

- If no real adapter is active, say `Searchable now. Local expert not trained yet.`
- Do not say `trained` for retrieval-ready clusters.
- Use `Learning` only for actual training/running state.

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
- Expert training failed.
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
- Do not call local experts `trained` unless a verified active adapter exists.
- Keep Bridge permissions and privacy visible.
- Keep backend degraded/auth states explicit.
- Add route-level QA notes when a tab gains new setup, diagnostic, or destructive behavior.

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
- No UI says a cluster expert is trained before verified LoRA adapter graduation.

