# Vault UI/UX Deep Audit and Delivery Plan

Date: 2026-07-24  
Status: implementation and evidence record; only items explicitly listed as removed or browser-verified in [Distillation pass: rendered and code inventory](#distillation-pass-rendered-and-code-inventory) should be treated as completed  
Scope: `apps/desktop`, current backend contracts, `docs/UI_RECOMMENDATIONS_BACKLOG.md`, and the historical interaction audit

## Executive conclusion

Vault already has a restrained, credible visual foundation. The largest problems are not its colors or typography. They are interaction truthfulness, duplicated surfaces, unsafe actions, weak degraded states, and views that expose controls or metrics without giving the user a dependable task path.

The next UI pass should therefore be a product simplification pass:

1. Make every visible control perform a real, testable action or remove its affordance.
2. Make offline, locked, stale, loading, partial, and failed states first-class.
3. Consolidate overlapping routes and duplicate representations.
4. Replace route-specific inspectors, status treatments, confirmations, and evidence panels with shared primitives.
5. Rebuild Map around authoritative, bounded, provenance-backed relationships. Do not continue presenting client-inferred word overlap as a knowledge relationship.

The intended result is not a more decorative application. It is an application that feels quieter because each page has one job, one primary action, and fewer false choices.

## Evidence used

- Read the current product register and the full UI recommendations backlog.
- Revalidated the historical 2026-06-01 interaction audit against current code.
- Reviewed every desktop route and the shared shell, command palette, graph, and inspector components.
- Performed a static scan across 443 `<button>` / `<Button>` occurrences and traced destructive handlers separately.
- Ran the current Vite renderer in a real browser at 1024×680 and at a 512 CSS-pixel width representing a 1024-pixel window at 200% zoom.
- Exercised the backend-offline state and captured Settings and Home screenshots in `output/playwright/`.
- Studied Zep/Graphiti’s current graph concepts and published graph-view behavior. Zep treats provenance as structural: episodes are source records, entities are nodes, facts are edges, and selecting an episode or fact exposes its source lineage. See:
  - [Zep and Graphiti](https://help.getzep.com/zep-vs-graphiti)
  - [Adding episodes](https://help.getzep.com/graphiti/core-concepts/adding-episodes)
  - [Context you can trace, filter, and trust](https://blog.getzep.com/context-you-can-trace-filter-and-trust/)

The installed Firecrawl connector returned an authentication error, so official Zep documentation and Zep’s own published material were read through the available web fallback.

## Audit health score

| Dimension | Score | Key finding |
| --- | ---: | --- |
| Accessibility | 2/4 | Basic semantics are present, but status announcements, disabled explanations, small targets, graph access, and false affordances remain inconsistent. |
| Performance | 2/4 | Graph code is lazy-loaded, but offline polling is noisy, several routes load large collections client-side, and Map computes all cluster pairs in the renderer. |
| Responsive design | 2/4 | Primary routes work near 1024 px, but the fixed 220 px shell does not collapse at 200% zoom and stacked inspectors create long multi-scroll pages. |
| Theming | 3/4 | The token system is coherent. Graph rendering and a few status/data-visualization colors bypass it or lack contrast-safe semantic pairs. |
| Anti-patterns | 2/4 | The visual language is restrained, but duplicated card/table views, decorative action icons, nested bordered regions, and dashboard-like metrics create product slop. |
| **Total** | **11/20** | **Acceptable foundation; significant interaction and information-architecture work required.** |

## Anti-pattern verdict

Vault does not look like a generic neon AI application. Its typography, palette, density, and Windows-oriented restraint are worth preserving.

It does, however, show a different kind of generated-product pattern: many surfaces look complete before their interaction model is complete. Examples include decorative ellipsis and close icons, fake selection boxes, non-switching inspector tabs, generic navigation standing in for specific actions, and repeated cards that restate information already visible in a table or inspector.

The correction is to remove UI until the remaining controls are unambiguous.

## P0 findings: trust and task completion

### P0.1 Destructive actions execute without confirmation or undo

Verified direct destructive calls:

- Sources deletes a source immediately in `_app.sources.tsx`.
- Chat index and chat detail delete sessions immediately.
- Bridge client deletion and extension revocation execute immediately.

Impact:

- A pointer slip can destroy or revoke user state.
- Source deletion copy does not explain whether the original local file is touched.
- Bridge revocation does not explain which integrations will stop working.

Required correction:

- Introduce one `InlineConfirmation` / `ConfirmAction` primitive.
- State the exact consequence in plain language.
- Use undo where the backend operation is safely reversible.
- Require typed-name confirmation only for high-impact vault/project deletion, not routine source removal.
- Restore focus after cancel/confirm and announce the result.

Acceptance:

- No destructive endpoint is callable from the desktop without an explicit consequence step.
- Disposable-vault browser tests cover confirm, cancel, failure, repeat click, and keyboard use.

### P0.2 The shell contains a confirmed dead button and several false affordances

Confirmed:

- The sidebar “Choose library” element is a real `<button>` with no handler.
- The profile footer shows a chevron but is not interactive.
- The Clusters table, cluster cards, and cluster inspector show ellipsis icons that are not controls.
- Sources shows checkbox-shaped squares that do not select anything and ellipsis icons that do not open a menu.
- Sources displays “Overview” and “Preview” as tabs, but both are static spans.
- Chat’s context rail shows ellipsis and close icons that do nothing.

Impact:

- Users learn that visual affordances are unreliable.
- “No dead buttons” cannot be achieved merely by attaching empty handlers; these elements must either gain a complete action or lose the affordance.

Required correction:

- Fix “Choose library” to open the actual library/vault workflow, or render it as plain path text with a Settings link.
- Make the profile footer a real menu with a defined inventory, or remove the chevron.
- Remove decorative ellipses, checkboxes, tabs, and close icons until their backed actions exist.
- Add an automated interaction inventory that fails on native buttons without handlers and maintain a reviewed allowlist for compound triggers.

Acceptance:

- Every button, menu trigger, tab, checkbox, disclosure, and action-looking icon has a named behavior.
- Every command palette item lands at the exact task it names.

### P0.3 Locking does not synchronously clear route state

The unlock/lock state is managed inside Settings, while the shell and route components retain sources, chats, citations, paths, and previews in React state. No shared lock-state boundary clears mounted route content when the vault becomes locked.

Impact:

- Sensitive content may remain visible after the user locks the vault until navigation or reload.
- This violates the product’s privacy promise even if subsequent backend requests are rejected.

Required correction:

- Move vault lock/readiness into one application-level state machine.
- On lock, cancel streams and requests, clear sensitive query caches and route state, close inspectors/popovers, and replace the outlet with a non-sensitive locked screen.
- Preserve only safe orientation such as vault display name.

Acceptance:

- Locking from any route removes source text, paths, citations, chat content, map labels, and previews within the same render turn.
- A Playwright test checks every sensitive primary route before and after lock.

### P0.4 Backend-offline behavior is noisy and sometimes appears stuck

The live offline pass produced repeated connection failures from:

- backend discovery across a wide port range,
- the shell’s 5-second job polling,
- 15-second saved-chat polling,
- 30-second cluster polling,
- route-specific data requests.

Map remained on “Building the map” while its request timeout was still pending. Settings exposed the raw error “Failed to fetch.” Previously loaded screens can continue showing content without a single authoritative degraded-state boundary.

Impact:

- The application looks unstable exactly when a local service is unavailable.
- Repeated probes waste resources and flood diagnostics.
- Raw transport language gives no recovery path.

Required correction:

- Add a shared connection coordinator with exponential backoff, route visibility awareness, and one discovery attempt at a time.
- Suspend collection polling while backend health is offline or the document is hidden.
- Abort route requests on navigation and resolve loading into a `DegradedState`.
- Keep safe cached data visible with a freshness label when allowed.
- Replace transport strings with action-specific copy and “Try again” / “Open Health.”

Acceptance:

- Offline mode produces no request storm.
- Every route exits loading within its bounded timeout.
- No user-facing screen renders raw fetch/HTTP/database errors outside Advanced diagnostics.

### P0.5 Map currently presents inferred similarity as if it were a real graph

`ClusterMap.buildEdges()` compares every pair of clusters and creates edges from shared client-tokenized words or shared media types. The inspector exposes a decimal “link strength,” even though the relationship is not returned by the backend and has no source provenance.

Impact:

- A shared generic word can become a visible relationship.
- Users cannot answer “why are these connected?” from real evidence.
- The graph contradicts Vault’s rules against fabricated confidence and client-inferred claims.
- Pairwise computation is O(n²) and does not scale.

Required correction:

- Stop labeling word/media overlap as a knowledge relationship.
- Until a provenance-backed graph API exists, show only authoritative cluster membership and source counts, or label similarity explicitly as a non-factual navigation hint with supporting matched terms.
- The target graph design is specified below.

Acceptance:

- Every visible edge has a backend ID, relationship kind, derivation mode, timestamp/freshness, and at least one inspectable source.
- No raw similarity/confidence number appears by default.

### P0.6 Disabled actions usually have no explanation

Many setup, model, source, chat, task, and native-file actions become disabled when the vault/runtime/native bridge is unavailable. The disabled control alone does not tell the user what prerequisite is missing.

Required correction:

- Standardize `AsyncActionButton` with loading state, failure feedback, and optional disabled reason.
- Where a disabled action is important, keep the reason visible next to it or in an accessible tooltip.
- Do not render actions that can never work in the current environment.

## P1 findings: information architecture and workflow

### P1.1 Search and Sources are competing libraries

Search currently includes:

- note/link/file/folder ingestion,
- source filtering and sorting,
- a card grid,
- source detail modal,
- source cover-image editing,
- current-library metrics,
- cluster navigation.

Sources contains:

- the same ingestion entry points,
- source search,
- a source table,
- project listing,
- a separate source inspector,
- source reindex/open/delete.

Required product decision:

- **Sources** owns capture, library browsing, inbox/review, organization, and source management.
- **Search** owns query, server-backed filters, ranked results, and inspection using the shared inspector.
- Search may offer one compact “Add source” entry, but it should not duplicate the capture toolbar or edit card art.
- Remove the project subview from Sources; Projects already exists as a first-class route.

### P1.2 Clusters renders the same collection three times

The index renders:

1. a cluster table,
2. a cluster card grid,
3. a persistent cluster inspector.

It also creates a cluster immediately with the generic name “New cluster,” making accidental duplicate records easy.

Required correction:

- Keep one scalable cluster list/table and one responsive inspector.
- Remove the duplicate card grid.
- Replace “New cluster” immediate creation with a small inline creation row or focused dialog that requires a name before persistence.
- Put suggestions in an explicit review queue with persisted dismissals and reasons.
- Make list selection and “Open cluster” distinct actions.

### P1.3 Timeline contains operational data that already belongs to Tasks and Bridge

Timeline merges sources, clusters, chats, Bridge requests, and background jobs. Tasks separately presents jobs; Bridge separately presents request history.

Required correction:

- Timeline becomes user-content history: sources added/indexed, chats, cluster/project changes, corrections.
- Tasks owns queued/running/failed/blocked/cancelled work.
- Bridge owns external access and audit events.
- Keep `/activity` as a redirect only during migration, then remove stale naming from navigation and commands.

### P1.4 Bridge is a 1,300-line administration page with no primary journey

Bridge mixes:

- enabled state and permissions,
- MCP setup,
- browser extension pairing,
- manual capture,
- approval review,
- two client systems,
- capture history,
- HTTP/CLI examples,
- rotation history.

Required correction:

- Lead with a three-step setup/status view:
  1. Enable external access.
  2. Approve or add a client.
  3. Confirm recent successful use.
- Put pending approvals immediately below status.
- Move manual capture and raw HTTP/CLI examples into Advanced tools.
- Use subnavigation inside Bridge for `Overview`, `Clients`, `Reviews`, and `History`; preserve the section in the URL.
- Do not stack all sections in one document.

### P1.5 Settings is internally organized but still too implementation-shaped

Settings has ten sections and 32 card-like regions. At 1024 px the section dropdown works, but backend failure displays raw transport text and important setup actions are surrounded by model/runtime terminology.

Required correction:

- User-facing groups: `Profile`, `Library`, `AI and search`, `Projects`, `Privacy`, `Support`.
- Keep current deep sections as nested anchors or progressive disclosures, not top-level peers.
- Move runtime URLs, model IDs, cache paths, job internals, and index identifiers into Advanced.
- Keep Health as task-oriented checks with exact repair links.
- Replace card stacks with setting rows and disclosures.

### P1.6 Chat has two competing context presentations

The chat index has a permanent “Vault context” rail with decorative controls, generic metrics, hard-coded prompts, and a “Recent sources” placeholder that never loads real sources. Chat detail has another permanent “Context used” rail with technical coverage/runtime detail.

Required correction:

- Remove the empty context rail from chat index.
- Keep scope and readiness directly attached to the composer.
- Suggested prompts should be data-backed and only shown when useful.
- In answers, show a compact evidence/freshness disclosure under the answer instead of a permanent metrics rail.
- Move technical coverage ledger and runtime codes behind “Answer details.”
- Confirm before deleting a chat.

### P1.7 Command palette labels do not match their outcomes

Examples:

- `New cluster` only navigates to Clusters.
- `Add link` only navigates to Sources.
- `Open vault` only navigates to generic Settings.
- Source results navigate to Sources without selecting the named source.

Required correction:

- Add explicit route search state for capture mode, creation mode, settings section, and selected entity.
- If an exact action cannot be performed, rename the command to the destination (`Open clusters`, `Open sources`).

### P1.8 Inspector behavior is inconsistent

Sources uses a persistent rail, Search uses a modal, Timeline uses a rail, Map uses a custom rail, citations use popovers, and project graphs use another inspector.

Required correction:

- Create one `EntityInspector` shell:
  - wide: right rail,
  - medium: inline region below the list/canvas,
  - narrow/zoomed: sheet or dedicated route,
  - persistent entity URL/search state,
  - standard title, state, provenance, actions, and close behavior.

## P2 findings: scale, accessibility, and polish

### P2.1 Fixed shell width remains too expensive at 200% zoom

At a 512 CSS-pixel viewport, representing a 1024-pixel desktop window at 200% zoom, the 220 px sidebar consumes roughly 43% of the screen. Content still renders, but becomes a narrow vertical strip and creates excessive page length.

Required correction:

- Collapse the sidebar below an effective content threshold, not only at phone widths.
- Preserve a compact rail or top command bar.
- Keep the current route and primary action visible.

### P2.2 Nested scroll regions and fixed graph heights create long, fragile layouts

Several routes switch from internal scrolling to page scrolling when their inspector stacks below. Map remains 720 px high before its inspector, which makes the selected detail far below the canvas at medium widths.

Required correction:

- Use one primary vertical scroll container per route.
- Move the selected graph inspector below the canvas as a bounded summary, not the full long rail.
- Use a sheet/dedicated detail when more information is requested.

### P2.3 Lists still load large collections into the renderer

Examples:

- Search, Map, Timeline, Home, and chat load broad source collections.
- Clusters loads only 200 source records while showing aggregate-like selected details, which can become incomplete.
- Inbox walks every source page in the renderer.

Required correction:

- Add server-side query, state, type, cluster/project, recency, and inbox filters.
- Add aggregate endpoints for counts.
- Paginate timeline and search on the server.
- Fetch inspector details and graph neighborhoods on selection.

### P2.4 Loading uses large blank spinners/text blocks rather than preserved layout

Required correction:

- Add `SkeletonRegion`.
- Keep previous successful data during refresh.
- Use indeterminate phase labels for work without measurable progress.

### P2.5 Status feedback is rarely announced

Most success/error messages are ordinary divs. Streaming completion, copy results, ingestion results, and mutation errors are not consistently announced.

Required correction:

- Add a shared status announcer.
- Use `role="status"` for polite completion and `role="alert"` only for immediate blocking errors.
- Avoid announcing every streaming token.

### P2.6 Repeated action targets are too small

Several graph controls and chat actions are 28–32 px. Backlog policy calls for 36–40 px graph targets.

### P2.7 Design tokens are good, but graph semantics are not tokenized

The main theme has strong contrast for body and muted text. Several graph colors and canvas RGBA values are hard-coded, and state colors do not provide complete foreground/background pairs for data visualization.

### P2.8 Route modules are oversized and difficult to validate

Approximate current route sizes:

- Settings: 2,310 lines
- Onboarding: 1,401 lines
- Bridge: 1,372 lines
- Chat detail: 1,124 lines
- Cluster detail: 1,024 lines
- Cluster map: 1,020 lines

Required correction:

- Split by user workflow and shared primitive, not by arbitrary visual subsection.
- Keep API/data hooks separate from view components.
- Add component-level behavior tests for each state machine.

## Zep-informed Map direction

### What to learn from Zep

The useful lesson is not “draw more nodes.” It is the graph’s semantic contract:

- source episodes remain inspectable,
- entities and facts are distinct,
- relationships have direction and meaning,
- temporal validity is preserved,
- selecting a node or edge reveals provenance,
- the graph is a debugging/exploration surface rather than an unexplained decoration.

### What Vault should not copy

- Do not expose a dense developer graph by default.
- Do not require users to understand ontology or graph-database terms.
- Do not render every source, fact, entity, and event at once.
- Do not treat graph navigation as the primary way to find information.
- Do not expose unverified model inference as an authoritative edge.

### Proposed Vault Map modes

#### 1. Overview mode

Default and bounded:

- cluster nodes only,
- node size based on real aggregate source/fact count,
- status shown through label plus icon, not color alone,
- authoritative cluster-to-cluster edges only,
- search and filters,
- list fallback always available.

If there are no authoritative cross-cluster edges, show separated clusters rather than inventing connections.

#### 2. Focus mode

Selecting a cluster fetches a bounded neighborhood:

- relevant entities,
- current facts/relationships,
- events where temporal order matters,
- source episodes that establish provenance,
- no more than a declared node/edge cap.

The user can expand one hop at a time. Expansion is a backend request, not a client-side traversal of the entire vault.

#### 3. Provenance inspector

Selection behavior:

- Cluster: summary, freshness, source/fact counts, related clusters with plain-language reasons.
- Entity: canonical name, aliases, categories, current relationships, source count.
- Fact/edge: readable statement, subject → relation → object, current/historical status, valid time, confidence class if meaningful, and exact supporting sources.
- Episode/source: source type, title, date, excerpt, cluster/project, and open/reveal actions.

#### 4. Temporal and trust representation

- Current relationship: solid line plus readable label.
- Historical/superseded: dashed line plus “Previous” label.
- User-confirmed: confirmation icon and text in inspector.
- Model-extracted: “Extracted locally” in inspector.
- Suggested/unverified: hidden by default; explicit filter required.

Color is secondary, never the only encoding.

### Required backend contract

Do not begin the final graph renderer before this read-only contract exists:

- `GET /api/v1/map/overview`
  - bounded clusters,
  - real counts,
  - authoritative relationship summaries,
  - lifecycle/freshness.
- `GET /api/v1/map/neighborhood`
  - root entity/cluster,
  - depth and node cap,
  - node kinds,
  - edge kinds/direction,
  - temporal state,
  - provenance IDs,
  - truncation metadata.
- `GET /api/v1/map/items/{id}`
  - inspector detail and cited origins.
- Server-side search/filter arguments.

Atomic-memory V2 entities and relations are a promising source, but only production-authorized, provenance-complete records may appear as graph facts. Until then, use authoritative cluster/source membership only.

## Target information architecture

Primary navigation:

1. Home
2. Search
3. Sources
4. Clusters
5. Projects
6. Chat
7. Map
8. Timeline
9. Tasks
10. Bridge
11. Settings

This keeps the current destinations but changes their responsibilities. After validation, consider moving Bridge and Tasks into a secondary “System” group rather than treating all eleven routes as equal-frequency daily destinations.

Route purposes:

| Route | One job |
| --- | --- |
| Home | Show what needs attention and provide the next useful action. |
| Search | Retrieve across the vault and inspect why a result matched. |
| Sources | Capture, review, organize, and manage source records. |
| Clusters | Review and manage memory spaces. |
| Projects | Inspect code-project readiness, freshness, and scoped questions. |
| Chat | Ask grounded questions and inspect answer evidence. |
| Map | Explore bounded, authoritative relationships with provenance. |
| Timeline | Review user-content history. |
| Tasks | Monitor and recover background work. |
| Bridge | Control external access and audit client use. |
| Settings | Configure the local product and recover readiness. |

## Shared components to build first

1. `AsyncActionButton`
2. `InlineConfirmation`
3. `StatusLabel`
4. `DegradedState`
5. `EmptyState`
6. `SkeletonRegion`
7. `EntityInspector`
8. `EvidenceDisclosure`
9. `ScopePicker`
10. `TaskProgress`
11. `PathText`
12. `ListToolbar`
13. `AppStatusAnnouncer`

These are not a component-library exercise. Each must replace at least two existing route-specific implementations in the same delivery phase.

## Phased implementation plan

### Phase 0: Freeze interaction truth

Goal: no dead or deceptive controls.

- Create the interactive-control inventory and allowlist compound triggers.
- Fix/remove the confirmed dead shell button.
- Remove decorative ellipses, close icons, checkboxes, and tabs.
- Correct command-palette names and deep links.
- Add click/keyboard tests for every primary action in a disposable vault.

Gate:

- No visible control lacks a verified state transition, navigation target, native action, or backend call.

### Phase 1: Safety and degraded states

Goal: the app remains trustworthy when something fails.

- Add shared lock/readiness state and synchronous sensitive-state clearing.
- Add connection coordination and polling backoff.
- Add route-level degraded states and request cancellation.
- Add confirmation to all destructive/revocation actions.
- Add status announcements and disabled explanations.

Gate:

- Offline, locked, and failure-state route suite passes with no raw errors or stale sensitive content.

### Phase 2: Shell and route simplification

Goal: fewer destinations feel like separate dashboards.

- Collapse the shell at 200% zoom/narrow widths.
- Make the vault footer/path/profile affordances real.
- Separate Timeline from Tasks/Bridge.
- Remove duplicate status copy from the global footer where it does not lead to action.
- Keep badges only for actionable failed/blocked work.

Gate:

- Every route has one-sentence purpose, one primary action, and one scrolling model.

### Phase 3: Sources, Search, and shared inspector

Goal: one library-management surface and one retrieval surface.

- Build server-backed filters and pagination.
- Implement `EntityInspector`.
- Remove Projects from Sources.
- Remove capture duplication and card-image editing from Search.
- Add persisted source selection/deep links.
- Add safe move/reindex/retry/remove workflows.

Gate:

- 10,000-source fixture remains responsive and selection/filter state survives navigation.

### Phase 4: Clusters and Home

Goal: make organization actionable without duplicate views.

- Replace cluster table + cards + inspector with one list + inspector.
- Add named cluster creation before persistence.
- Add persisted suggestion decisions and reasons.
- Make Home empty-vault and attention states contextual.
- Link every Home activity item to its exact entity.

Gate:

- No generic “New cluster” records are created accidentally.
- Home contains no vanity or incomplete counts.

### Phase 5: Unified grounded answer experience

Goal: scope, freshness, and evidence live with the answer.

- Build shared answer/evidence components for vault, cluster, project, and Bridge outputs.
- Remove permanent technical metrics rails.
- Preserve drafts during backend/runtime interruption.
- Distinguish no evidence from no synthesis runtime.
- Add stale/deleted/reindexed citation behavior.

Gate:

- The same answer fixture renders consistently in all scopes and exposes only evidence actually used.

### Phase 6: Settings and Bridge distillation

Goal: remove endless administration pages.

- Regroup Settings around user tasks with Advanced disclosure.
- Split Bridge into Overview, Clients, Reviews, and History.
- Promote pending approvals and failed readiness; demote raw examples.
- Use shared setting rows, statuses, progress, and confirmations.

Gate:

- A new user can connect one MCP client without scrolling through unrelated controls.
- Every Health failure deep-links to the exact repair surface.

### Phase 7: Authoritative Map rebuild

Goal: a Zep-informed graph that earns user trust.

- Add the overview/neighborhood/detail backend APIs.
- Replace client-inferred pairwise edges.
- Implement overview, focus, provenance inspector, temporal states, and list fallback.
- Fetch bounded neighborhoods on demand.
- Respect reduced motion and keyboard navigation.

Gate:

- Every edge is provenance-backed.
- 1,000-cluster/large-vault scale test does not fetch all sources or compute all pairs in the renderer.
- Graph, list fallback, and inspector expose equivalent essential information.

### Phase 8: Performance, accessibility, and packaged validation

Goal: release proof.

- Profile route renders and polling.
- Code-split optional graph/Figma/integration code.
- Add skeletons and preserve cached data during refresh.
- Run WCAG AA, keyboard-only, 1024×680, 125–200% zoom, long-text, reduced-motion, and dark-theme checks.
- Run rowdy-user flows: rapid navigation, double clicks, interrupted streams, resize, lock/unlock, and offline recovery.
- Validate the packaged Electron build, not only Vite.

Gate:

- Re-run this audit and reach at least 17/20 with no P0 findings.

## Backlog disposition

Adopt now:

- interaction truthfulness,
- 200% zoom and long-content QA,
- lock-state clearing,
- destructive confirmation,
- real progress only,
- Timeline/Tasks separation,
- shared inspector/evidence/status primitives,
- server-side scale work,
- skeletons,
- graph list fallback and bounded fetching.

Modify:

- Keep all current primary destinations during the first simplification pass, but group Tasks/Bridge as secondary if usage tests support it.
- Keep Map as an overview, but evolve it from cluster similarity toward provenance-backed context relationships.
- Keep recent clusters/chats in the shell only when space and real recency justify them.

Already partly completed:

- source inbox route,
- state-aware Home summaries/icons/timestamps,
- Settings section URLs,
- guided MCP setup,
- cluster summary generation,
- chat starter prompts,
- Map empty state,
- lazy-loading the force-graph renderer.

Defer until backend support exists:

- source bulk actions,
- rich graph neighborhood expansion,
- authoritative cross-cluster relationship edges,
- persisted graph views,
- retry buttons for job types the backend does not mark retryable.

Reject:

- adding more top-level routes,
- decorative dashboard totals,
- exposing raw graph confidence/link-strength numbers,
- loading every source to construct Map,
- filling missing backend fields with client-inferred product claims.

## Validation matrix

Every primary route must be tested in:

- empty vault,
- populated vault,
- mixed waiting/processing/indexed/failed data,
- backend offline,
- vault locked,
- local chat unavailable,
- memory search unavailable,
- active task,
- stale project/index,
- long names/paths/errors,
- 1024×680,
- 1280×820,
- 1440×900,
- 125%, 150%, and 200% zoom,
- reduced motion,
- keyboard-only navigation.

For each interactive control verify:

- accessible name,
- visible focus,
- click and keyboard activation,
- idle/loading/success/failure state,
- disabled reason where necessary,
- double-click behavior,
- exact side effect,
- recovery or undo,
- focus destination after completion.

## Definition of done

The UI pass is complete when:

- no action-looking element is decorative,
- no destructive action is immediate,
- no route can remain indefinitely in loading,
- no route shows raw transport/backend errors by default,
- locking clears sensitive content synchronously,
- Search and Sources no longer duplicate library workflows,
- Clusters no longer renders the same collection in multiple formats at once,
- Timeline does not duplicate Tasks and Bridge,
- Bridge and Settings do not require endless scrolling through unrelated sections,
- Map shows only authoritative, inspectable relationships,
- all routes pass the validation matrix in packaged Electron.

## Frontend layout contract

This contract applies to every authenticated route and every new component. A feature is not
finished merely because its controls work; it must also compose with the rest of the product.

- Use the shared 4-point spacing scale. Related controls use 8–12px gaps, component interiors
  use 16–24px insets, and independent page sections use at least 32px separation.
- Do not reduce spacing or typography simply to fit more content. Collapse, wrap, paginate, or
  disclose secondary information progressively instead.
- Preserve hierarchy in this order: page heading, section heading and optional explanation,
  primary content, metadata, then secondary actions.
- Use `ProductSection`, `ProductSectionHeader`, and `ProductSectionStack` for standard page
  sections. A route may depart from them only when its task requires a genuinely different
  structure, such as chat or the knowledge map.
- A section header has one title, at most one short explanation, and a clearly separated action
  area. Do not squeeze unrelated filters, counts, badges, and actions into the title line.
- Use one-dimensional lists for chronological activity. Multi-column timelines are prohibited
  because they obscure event order and create false visual relationships.
- Align repeated rows to the same content inset and minimum height. Metadata should occupy a
  predictable column or sit beneath the primary label at narrow widths.
- Avoid nested cards. Within a section, prefer dividers and whitespace; use an inner bordered
  surface only when the item itself is independently actionable.
- Verify every changed surface at desktop and narrow-window widths with no horizontal overflow.
  Visual review is required in addition to type checking and component tests.

## Distillation pass: rendered and code inventory

Date completed: 2026-07-24

This pass followed the earlier audit with a stricter question: if a surface already has a clear
destination, what additional UI is making the task easier rather than merely repeating it?

### Removed in this pass

- Removed the cluster-detail right rail. Its close glyph was a plain `X` icon with no button,
  state transition, or close handler. The rail repeated source counts, activity, top sources, and
  memory-profile status already available in the detail workspace.
- Removed the cluster-index inspector. Each cluster row now opens the actual cluster detail route;
  the list no longer requires a select-then-open two-step flow or reserves 340px for repeated data.
- Removed the cluster-detail `Map` tab. It rendered a synthetic radial source layout and a second
  source list even though Vault already has an authoritative Knowledge Map route.
- Removed duplicate cluster overview tables and the four-cell “Bundle status” card. The overview
  now has one source list, one chat list, and a compact metadata line.
- Made recent chat rows real deep links. The earlier arrow icon suggested navigation while the row
  itself was inert.
- Removed the global “Saved chats” block from the application shell. Chat already owns complete
  conversation navigation, so showing the same list twice added another scroll region and another
  “new chat” action.
- Removed the always-visible Settings utility rail. Storage, backup, search-index rebuild, and
  deletion actions now live in Library storage, Memory search, and Advanced respectively.
- Removed the unreferenced 1,020-line legacy `ClusterMap` implementation. The current map route uses
  `KnowledgeMap`.
- Removed 29 generated UI primitive files that had no import anywhere under `apps/desktop/src`.
- Removed the unreferenced Figma-export source utility. The package and workflow document remain
  listed below until dependency/document cleanup is explicitly accepted.

### Rails and inspectors that remain justified

- **Sources:** keep an inspector because there is currently no dedicated source-detail route.
  Improvement still needed: do not reserve the rail when nothing is selected.
- **Map:** keep selection detail because it explains the currently selected canvas node or edge.
- **Timeline and Tasks:** keep selection detail because the route is a master/detail workflow.
- **Chat:** keep one conversation list. The duplicate global saved-chat list has been removed.
- **Settings:** keep section navigation. The unrelated utility rail has been removed.

### Confirmed stale code to remove next

The strict TypeScript unused-symbol pass found the following code that normal type checking does not
currently reject:

1. **Cluster detail:** an entire embedded `ProjectWorkspace`, plus `MetricGrid` and `Divider`, remain
   in `_app.clusters.$clusterId.tsx` even though project clusters redirect to the dedicated Projects
   route. This is the highest-value next deletion.
2. **Search:** dormant capture/edit state and handlers remain for add-file, add-folder, note, link,
   drag/drop, and card-image editing. Search no longer renders those workflows; Sources owns them.
3. **Chat detail:** unused citation, warning, runtime-state, coverage-summary, and `ClusterDot`
   presentation values remain from an older permanent-context treatment.
4. **Small residue:** the Home indexed count, Settings suggested model, Timeline icon, Chat index
   icon, Tasks parameter, and Onboarding selected-model value found by the pass were removed.
   Search still has unused imports alongside the larger dormant capture workflow described above.
5. **Dependency residue:** `@figit/dom-to-figma` is now unreferenced. Remove it from the desktop
   package and lockfile after confirming that Figma export is no longer a supported developer
   workflow.
6. **Documentation residue:** `docs/FIGMA_EXPORT_WORKFLOW.md` becomes stale if that workflow is
   formally retired.

### Overengineered surfaces requiring a product-level reduction

These are not safe one-line deletions; their responsibilities should be reduced before code is
removed:

- **Search vs Sources:** Search still carries the data/state footprint of ingestion even though its
  user job is retrieval. Delete the dormant handlers and keep capture in Sources.
- **Bridge:** 26 buttons are visible in a typical populated desktop render. Split routine setup and
  status from advanced client administration instead of exposing all systems at once.
- **Settings:** the right rail is gone, but the route remains a very large card stack. Preserve the
  section navigation while extracting task-focused panels and moving runtime identifiers to
  Advanced.
- **Sources empty inspector:** collapse the unused rail until selection, or add a persistent
  source-detail URL so selection is recoverable.
- **Global recent clusters:** retain only if user testing shows that it shortens a frequent journey;
  otherwise the Clusters destination and command palette are sufficient.
- **Permanent bottom status strip:** keep actionable service/task state, but remove shortcut and
  privacy slogans if they merely repeat onboarding or Settings.

### Render verification

The authenticated routes Home, Chat, Search, Sources, Projects, Clusters, Map, Timeline, Bridge,
Tasks, Settings/Profile, Settings/OCR, and Settings/Storage were rendered at 1440×900 and 768×900.

- No document-level horizontal overflow was detected.
- No visible unlabeled button or link was detected after the shell duplicate was removed.
- No unclipped text overflow was detected by the automated geometry pass.
- No browser console errors were recorded.
- The interactive-control audit passed across all 46 remaining TSX files.
- Standard TypeScript type checking passed.

This geometry pass does not replace packaged Electron, 200% zoom, keyboard-only, reduced-motion, or
screen-reader validation. Those remain release gates rather than claims made by this audit.
