# Project Context

## 2026-07-31 — desktop workflows, nested sources, and connected assistants

- Profile settings show the active library name and path. The command palette adds
  **Health status** (`Ctrl+Shift+H`), which opens a draggable bottom-right panel
  with the latest backend, library, local-chat, and background-work state.
- Chat answers use a safe structured Markdown renderer for headings, lists,
  emphasis, strong text, inline code, blockquotes, and fenced code. Model output
  no longer exposes supported `#` and `*` delimiters as plain text, and raw HTML
  remains inert.
- Folder imports retain `import_root_path` and `import_relative_path` as the
  navigation authority. Sources exposes a bounded folder-tree endpoint and lets
  users browse nested directories without flattening child folders into the
  selected root.
- Bridge is organized around Connect, Access, Review, Activity, and Manual tools.
  Read-and-save connections use the existing MCP capture tools to send an external
  assistant's answer through trust review, indexing, and normal retrieval without
  requiring manual copy/paste. Manual capture remains an explicit fallback.
- Home keeps Quick actions in the second default section. Timeline supports manual
  refresh and otherwise polls once per minute. Tasks emphasizes active work and
  removes stale detail when filters change.
- Focused validation is green: desktop TypeScript, 6 chat-presentation tests,
  30 nested-folder and Bridge backend tests, and four rendered workflows covering
  Profile/Health, Markdown, nested folders, and Bridge. No release build was made.

Last updated: 2026-07-31

## 2026-07-30 — TurboVec distribution correction

- `turbovec==0.8.0` is part of backend, development, and portable Windows runtime dependencies.
- Package creation, package layout auditing, packaged startup smoke, and clean-machine validation reject a missing real `IdMapIndex` runtime.
- Vector search defaults to `auto`. Vaults below the threshold or without a successful Phase-C approval remain on exact search.
- The sidecar remains derived state under the vault path; SQLite remains authoritative and unhealthy sidecars fail closed.

## 2026-07-30 — current implementation

- Chat routing is model-directed and context-aware: general questions bypass retrieval, while questions about saved objects receive bounded context.
- Retrieved evidence has an explicit answer policy. Hostile evidence is extract/refuse only; contradictions are explained; weak relevant evidence permits qualified reasoning; sufficient evidence receives normal grounded synthesis.
- Streaming and non-streaming paths enforce the same trust and synthesis gates. The policy is model-agnostic and does not depend on one local model's wording or behavior.
- Trusted profile identity is available without allowing generic assistant refusals or the current assistant turn to become authoritative personal memory.
- Cluster organization operates only on active-vault clusters. Ready sources may remain conservatively unclustered, and users can create/delete clusters and assign or move documents directly from Sources.
- Empty chat clusters are removed after the last contained chat is deleted.
- Semantic enrichment coalesces cluster-profile work after a source wave, avoiding a costly refresh for every enriched source. Job progress and finalization remain observable and restart-safe.
- Project freshness and Odin synchronization compare against the active snapshot, eliminating Git-HEAD-only false warnings for already indexed changes.
- Chat displays supported inline Markdown, including bold text, in saved and streaming answers.
- Focused verification is green: 39 answer-policy/route tests plus 3 subtests, 6 semantic-batching tests, 5 chat-presentation Node tests, desktop TypeScript checking, and one focused rendered Markdown check. Full regression and release packaging are still required promotion gates and were not run as part of this focused pass.

Last updated: 2026-07-30

## 2026-07-29 — deep-audit implementation

- Desktop window controls now own one invisible 150-by-44 CSS safe rectangle. Application headers, Chat, onboarding, startup, and repair surfaces use the same 138-pixel control width, 32-pixel control height, and 12-pixel buffer. Tests reject the retired route-specific margin classes.
- Project indexing has one activation writer. Historical monolithic jobs are terminated with an explicit result and requeued through discovery, structure, retrieval staging, and atomic activation.
- Public API and chat-stream failures now use stable, short messages with local diagnostic IDs. Validation payloads, paths, OS errors, and exception text stay out of renderer responses.
- Odin connection history is cursor-paginated and lazy. Active counts come from an exact bounded count query rather than the first page.
- Chat opens with metadata plus the newest 80 timeline items, loads older pages without replacing visible history, and polls only newer deltas.
- Standalone clustering uses persisted, versioned candidate profiles and bounded review work. Ambiguous imports remain unclustered, project sources are excluded, manual identity is protected, decisions are keyed to source and profile evidence, and abandoned automatic clusters are removed.
- Cluster organization backfill runs in bounded batches through Tasks with progress, pause, resume, cancellation, and failure records.
- Scale contracts now cover 10,000 sources, 1,000 clusters, 2,000 chat messages, and 1,000 Odin clients.
- Final verification is green: 868 backend tests passed, 141 desktop behavior tests passed, the production frontend build and Python compilation passed, and the renderer-safety, interactive-control, package-layout, and diff-whitespace audits passed. The Odin release scale test remains an explicit opt-in gate, and the TurboVec benchmark was skipped because TurboVec is not installed in the development environment.

## 2026-07-29 — project retrieval and on-demand graph workspace

- Project activation now keeps `sources.cluster_id` and `source_chunks.cluster_id` in the same transaction. Schema migration 16 repairs active chunks from existing projects, restoring evidence for both Odin context and project-scoped chat without re-importing folders.
- Requested architecture graphs no longer render as small chat artifacts. Project and chat requests lead to the on-demand `/project-map` workspace, which is intentionally absent from normal navigation.
- The project map provides bounded expansion, direction controls, graph/tree modes, wider layout spacing, source inspection, key areas, and deterministic evidence-backed flow summaries.
- Knowledge-map overview and neighborhood results can be expanded, and map details occupy space only after selection.
- Runtime backend URLs received by the renderer are restricted to credential-free loopback HTTP origins before any authenticated probe.
- The local deep-audit records are intentionally excluded from Git; current behavior is summarized here and in `docs/OVERALL_CONTEXT.md`.

Last updated: 2026-07-29

## Purpose

This is the lean operating brief for Vault. It records current truth, the active project phase, and immediate priorities. Detailed history, experiments, and validation results belong in `docs/OVERALL_CONTEXT.md`; public benchmark methodology belongs in `BENCHMARK.md`.

## Product

Vault is a local-first Windows context-management layer. It turns a user's files, notes, links, screenshots, transcripts, folders, and codebases into reusable, cited context for AI.

- Desktop: Electron and React in `apps/desktop`
- Backend: FastAPI in `backend`
- Storage: explicit local vaults backed by SQLite and local indexes
- External access: Bridge, MCP, local HTTP API, and CLI
- Codebase context: Odin project indexing, retrieval, scoped chat, and request-only graph/tree artifacts
- Current version: `0.1.12`

## Current Project Phase

Vault is in **pre-release stabilization and productionization**.

The scoped RAG migration, temporal memory foundation, Odin project workflow, bounded context pipeline, and primary desktop surfaces are implemented. The project is no longer deciding its core architecture. Current work is about proving release reliability, productionizing the strongest retrieval improvements, improving measured quality without benchmark-specific behavior, distilling the UI around real user journeys, and finishing clean Windows packaging.

The reviewed 0.1.9 product, packaging, CI, and documentation work is published on `main`. GitHub CI run `30182242079` passed every automatic job for product commit `f36f75e1959ac40b783303316265974f037ae1fb`. A development/test NSIS installer completed install, shortcut, registry, launch, and uninstall validation. Version 0.1.9 remains pre-release because signing, Windows account-separation proof, and a release build on the latest source revision remain outstanding.

## July 29 Project Import, Locking, And Large-Source Navigation

Projects is no longer CLI-only. The Projects page can select one or more local
folders, register each through the same project authority used by Odin, and start
the immutable snapshot pipeline. Odin remains available for terminal and IDE
workflows. Project-created clusters and job triggers now use neutral project
language so behavior is truthful regardless of which entry point registered the
folder.

Large project retrieval now commits resumable batches of 12 files. Each commit
publishes the current completed/total heartbeat, so a project with hundreds of files
does not appear frozen during one long transaction. The activation job reports that
it is waiting for project indexing instead of exposing the scheduler's
`blocked_by_dependency` wording. Candidate snapshot sources are excluded from
Sources and its aggregates until atomic activation, preventing temporary
unclustered duplicates. Active projects and explicitly imported folders with 20 or
more sources appear as one folder on the Sources page; opening the folder provides
the normal source rows and actions with independent pagination and filters. Folder
membership is recorded during the durable import job rather than guessed later from
file names.

The locked-library route now accepts the passphrase directly and keeps validation
errors beside the field. Recovery and passphrase reset remain in Privacy settings.
Ctrl+L locks the active secured vault immediately, and the command palette exposes
the same action so the shortcut is discoverable.

## July 29 Workflow Reliability And Odin Setup

The latest source closes the reported workflow gaps across suggested organization,
chat, ingestion, source metadata, operational details, model selection, and Odin
setup. Suggested moves are now durable backend decisions, appear in the default
Focused Home layout, produce a Clusters badge and a small notification, and move the
source only after backend confirmation. Source and cluster metadata are generated
during ingestion, while automatic cluster names can improve without overwriting
names chosen by the user.

Chat attachments are stored and displayed as file attachments instead of prompt
text. A generation continues after the user leaves its page, appears as running in
conversation history, and produces an Answer ready notification when it finishes.
Reopening the chat reconnects to durable generation state. Successful completion
also synchronizes temporal memory immediately, closing the gap behind an empty
Memory history panel.

Sources now expose type and status filters. Import progress and failed filenames
remain visible outside Sources, and Tasks lists per-file failures. Task, Timeline,
and source detail panels consume no default width and open only after selection.
Folder sync replaces the nonfunctional Local imports presentation and can create a
watched-folder import through the native desktop picker.

Model rows are hidden until requested. Compatibility copy reflects whether a model
can actually be used for chat, and unmeasured recommendations are labeled as
catalog estimates rather than presented as benchmark evidence. Recommendation
ranking remains based on the detected hardware, model requirements, approved
catalog data, and measured results when available.

Odin now supports two Settings installation paths. The recommended Vault-managed
launcher chooses a writable location from local application data, roaming
application data, Electron user data, or the user profile instead of depending on
one unsupported path lookup. The optional `uv` path installs the packaged backend
as an isolated tool. Pairing starts a detached visible PowerShell process so the
desktop does not freeze while waiting for approval. Users can also select and add a
local repository through Vault before using the CLI.

Validation passed desktop TypeScript and 128 Electron tests, the production
renderer build, Python compilation, renderer security, interactive-control audit,
diff hygiene, and 837 backend tests. Two environment-dependent backend tests were
skipped. One existing OCR packaging contract remains outside that count because
`backend/bin/ocr/README.md` is deleted in the current working tree. No Windows
package was rebuilt and no release claim is attached to this source-only result.

## July 29 Local Model Acceleration

The packaged local-model runtime was CPU-only and launched without explicit thread
tuning. On the current i7-12700H and RTX 3060 Laptop system, Qwen3-4B Q4_K_M
generated about 5 tokens per second. Windows packaging now stages pinned,
checksum-verified CPU and CUDA 12.4 variants of llama.cpp. Vault selects CUDA on a
supported NVIDIA GPU, uses automatic layer fitting, and falls back to the CPU
runtime when GPU startup is unavailable.

Generation and batch thread counts now follow physical and logical CPU capacity,
with bounded overrides, while context remains bounded at a 4096-token default.
Runtime replacement also removes only exact stale Vault processes that match the
packaged executable, GGUF model, and loopback host; this prevents duplicate model
servers without terminating unrelated llama.cpp sessions. Packaging cleanup uses
the same path ownership principle before retrying removal of locked output.

A live staged-runtime test on the affected model reached 38.75 generated tokens per
second and 76.03 prompt tokens per second while using 3583 MiB of VRAM. Focused
runtime tests, all selected backend tests, Electron behavior tests, TypeScript,
renderer production build, renderer security, package layout security, and script
syntax checks pass. The Windows package remains intentionally unbuilt pending the
owner-managed rebuild; the CUDA payload adds roughly 1.2 GiB uncompressed before
installer compression.

## July 28 0.1.11 Release Candidate

PR #5 is reviewed and merged into `main`. It restores grounded local RAG, hardens
Odin pairing during indexing load, makes vector repair durable per source, repairs
the packaged OCR manifest, and keeps the first-use tour inside small viewports.
Release follow-up work bounds pairing refreshes in SQL, safely launches Odin from
Windows paths containing apostrophes, and makes the model-download concurrency test
independent of host disk space. Version metadata is now `0.1.11`; the Windows
package and GitHub release remain owner-run steps.

## July 28 Packaged Preload And Startup Chrome Repair

The latest unpacked build exposed a packaged-only startup failure. Electron's
sandboxed preload attempted to require two local CommonJS helpers from
`app.asar`; sandboxed preloads cannot load arbitrary local modules, so the preload
failed before exposing `cmlDesktop`. The renderer therefore could not signal
readiness, external drops lost their native-path bridge, and every custom window
control or repair action became unavailable. The preload entry is now
self-contained while `sandbox: true`, context isolation, and disabled renderer Node
integration remain intact. A regression assertion rejects future local preload
imports.

The opening-library document and the repair document now share visible, accessible
minimize, maximize/restore, and close controls. Repair screens load from a packaged
local HTML file instead of a generated `data:` URL, receive structured state through
`loadFile`, and bind actions through external scripts under a restrictive CSP. This
also removes silent inline handlers and the oversized recovery URL from new runtime
logs. Desktop TypeScript, all 118 Electron tests, the production renderer build,
diff hygiene, and rendered 1280×820 startup/repair checks pass. The Windows package
still awaits the owner-managed rebuild.

## July 28 Error-State Branding And Copy

Every dedicated startup, repair, route-not-found, React error-boundary, and
server-render failure screen now uses the same `Container.svg` wordmark as Opening
your library and onboarding. The old `logo.svg` and application references to `Frame 8.png` were
favicon reference to the legacy mark, and the embedded emergency startup artwork
were removed. If the startup document is missing, Vault now opens the branded
repair document; only a text-only bounded page remains for a package missing both
documents.

Primary error copy now states what failed and the next safe action in plain
language. Backend and renderer messages, paths, and logs remain available through
Copy details instead of appearing in the main explanation. The repair page keeps
the frameless window controls and uses a readable wordmark, fixed type sizes, and
the existing restrained product colors. All 122 Electron tests, desktop TypeScript,
the renderer HTML safety audit, the interactive-control audit, and the production
renderer build pass. The recovery page was also visually checked at 1280x820. The
package still awaits the owner-managed rebuild.

## July 28 Configurable Home And UI Distillation

Home is now a configurable working overview instead of four equally weighted,
partly repetitive dashboard groups. The default Focused preset contains Ask Vault,
actionable Needs attention, a unified Continue working feed, recently active
clusters, and a restrained quick-action row. Library and Activity presets expose
the alternate source, inbox, type, timeline, task, and conversation views without
adding metric tiles or decorative charts.

Type and Sort controls apply to Home content. Customize is a non-modal popover with
layout preset, density, list/grid view, section visibility, keyboard-accessible
ordering, and reset. The panel has a bounded, scrollable body and pinned footer so
Reset remains reachable in shorter windows. Preferences are schema-validated and
stored locally under the active vault/profile identifier; malformed or older local
state falls back safely. Source-type totals use one grouped backend query rather
than issuing a request for every type.

The sidebar now uses the exact `Container.svg` wordmark from the opening-library
screen, limits recent items, and combines saved chats and clusters under one Recent
group. Shared section/table labels no longer use small all-caps tracking, decorative
cluster-edge stripes were removed, and dense Settings explanations were moved under
their headings or into optional disclosures. Library unlock now reports only
Unlocked, Locked, or Not protected instead of repeating technical state/protection
copy.

Validation is green: desktop TypeScript and all 118 Electron tests pass; focused
backend count, pagination, and activity-scale tests pass; Python compilation and
diff hygiene pass; and the production renderer build succeeds. Rendered Playwright
checks covered the default and Library presets, the full Customize interaction,
reset accessibility at 1280x800, and the compact 760x760 layout. The web-only
rendered harness showed expected local-service connection failures because it does
not carry the Electron backend runtime. The Windows package remains intentionally
unbuilt pending the owner-managed rebuild.

## July 28 Window-Control Exclusion Zone

The invisible frameless titlebar remains part of the product layout and route content
still begins at the top of the window. A compact 150×44 px no-go area now surrounds
the 138×32 px minimize, maximize, and close group, adding a 12 px buffer to its left
and below without introducing a full-width strip.

Top-edge action groups use one desktop-only exclusion utility that moves them left
of this area while leaving their vertical rhythm and all lower page content
unchanged. Search's Manage sources action and the corresponding top actions on Home,
Sources, Map, Projects, Tasks, Bridge, and Clusters use the same contract. Narrow
responsive layouts do not receive the page-action offset because their actions
already stack below the window controls. Their centered logo stays centered while
the status indicator stops before the same exclusion zone. Rendered desktop and
compact checks, all 113 desktop tests, TypeScript, the production web build, and the
interactive-control audit pass.

## July 28 Durable File-Import Progress

File and folder imports now run as durable background jobs rather than a renderer-only
loop. Sources shows exact processed/total counts, percentage, current file, bounded
failure details, and a progress bar where its former “Importing files” message
appeared. A second compact progress surface is mounted above application routes, so
the same authoritative job remains visible after navigation. It can be dismissed
without affecting the import.

Users can pause and resume imports or stop them after a confirmation. Pause and stop
prevent new work from starting; up to four files already being processed may finish
and remain safely imported. Per-file completion is persisted, so a backend restart or
resume skips confirmed work. One active batch is allowed per vault, duplicate paths
within a batch are removed, filesystem paths are not exposed in displayed failure
details, and batches remain bounded by the desktop's 10,000-file scan limit.

The Sources detail panel no longer reserves right-side space before a source is
selected. At desktop width it transitions from a zero-width grid track to the
existing 326 px inspector, provides an explicit close action, and disables motion
when reduced motion is requested. Narrow layouts retain a single content column.

Focused scheduler and import tests, all 113 desktop behavior tests, and all 407
selected quick-tier backend tests pass. TypeScript, the production web build,
renderer HTML safety, interactive-control auditing, and Python compilation also
pass. Rendered QA covered 1440×900 and 900×800, navigation persistence,
pause/resume, confirmed stop, dismissal, progress accessibility, inspector
open/close, and a clean console. It used an intercepted local API and did not import
real files. The Windows package remains intentionally unbuilt pending the
owner-managed rebuild.

## July 28 Settings Feedback And Single-Source Cluster Moves

Settings action feedback now uses the application-wide notification viewport instead
of occupying space above the page. Notifications are fixed to the bottom center of
the visible app frame, remain readable while the page scrolls, start fading after
five seconds, and are removed after 5.5 seconds. They retain manual dismissal and
accessible live-region semantics. Repeated Settings polling errors are deduplicated
so an unavailable service cannot create a new notification every six seconds.

Cluster detail now supports moving one source without merging its whole cluster. The
Sources tab exposes a Move action and a destination dialog containing other clusters
from the same vault. The existing authoritative source-update API performs the move,
validates vault ownership, refreshes old and new cluster profiles, invalidates
retrieval caches, and reindexes an indexed source. The renderer removes the source
from the current cluster only after the backend confirms the destination. Failed
moves remain visible in the dialog and can be retried.

Focused backend and Electron regressions pass. The complete desktop behavior run
passes 110/110 tests, the quick backend tier passes 403/403 selected tests, and
TypeScript, the production build, renderer HTML safety, and interactive-control
audits pass. Rendered checks cover notification expiry, polling deduplication, valid
destination selection, successful source removal, narrow-window usability, and a
clean console. Rendered move validation used an intercepted local API and did not
mutate a real vault. The Windows package remains intentionally unbuilt pending the
owner-managed rebuild.

## July 28 Settings Information Architecture Cleanup

The Settings renderer previously mapped both Local imports and Evidence retention to
Library & security and Advanced, so the same live controls appeared under two
navigation destinations. Each card now has one owner: Local imports is in Library &
security, while Evidence retention is in Advanced. No state or action was duplicated
or removed.

A regression rejects any Settings card condition that targets multiple tabs. Focused
coverage passes 2/2 cases; desktop TypeScript and all 104 Electron tests pass; the
production renderer build, renderer HTML safety audit, and interactive-control audit
pass. Rendered navigation was verified at 1280×720 and 900×800.

## July 28 Odin Launcher Install Fix

Odin installation failed before writing the launcher because the desktop main process
requested `app.getPath("localAppData")`, which is not a supported Electron path name.
The launcher configuration now uses `%LOCALAPPDATA%\CML\bin` when the absolute
environment path is available and derives the equivalent Local directory from
Electron's supported `appData` path as a safe fallback. Install and status therefore
share the intended per-user location without relying on an invalid Electron API.

Odin install and pairing failures are also cleaned at the preload boundary, so the UI
shows the actionable cause rather than Electron's
`Error invoking remote method ...` wrapper. Focused launcher and IPC coverage passes
9/9 cases; desktop TypeScript and all 102 Electron tests pass; the production renderer
build, renderer HTML safety audit, interactive-control audit, and diff hygiene pass.
The Windows package remains intentionally unbuilt pending the owner-managed rebuild.

## July 28 Package-Launch And Model-State Fixes

The July 28 development package exposed a deterministic launch failure in both the
unpacked executable and an installed copy. The main process embedded the 1.64 MB
onboarding wordmark inside an HTML `data:` URL; the resulting roughly 2.2 MB startup
URL was rejected by Chromium with `ERR_INVALID_URL (-300)` before backend startup or
window display. Startup now loads a small `electron/startup.html` document from
`app.asar`, and that document references the same bundled `Container.svg` used by
onboarding. A bounded inline mark remains available if the startup document is
missing. Runtime logging now truncates oversized URL/stack fields, and the packaged
launch smoke test exits promptly with the process exit code and a bounded log tail.

The model onboarding and settings paths now derive readiness from canonical backend
model state rather than treating import completion as activation. Duplicate imports
are reconciled by model identity and artifact path, unusable entries are not presented
as ready, and an already imported usable model can be selected without importing it
again. Regression coverage includes duplicate legacy records and interrupted or
inactive imports.

Current source validation after these changes is clean: the full backend suite passed
with 816 tests and 2 optional skips; desktop TypeScript and all 94 Electron tests pass;
the production renderer build and renderer HTML safety audit pass; and diff hygiene
passes with line-ending warnings only. The existing July 28 installer/unpacked
artifact is intentionally still the failing pre-fix build. The owner-deferred rebuild
and the complete post-rebuild package gates remain required.

## July 28 Profile, Startup, And Chat Reliability Fixes

The durable onboarding profile is now the single authority for the user's display
name and avatar. Settings saves through Electron setup state, the sidebar subscribes
to the same state, and profile media resolves through the managed-media API. The
vault folder name is no longer used as the user name. The startup progress page uses
one onboarding wordmark rather than rendering a second duplicate logo.

External file drops now cross Electron's isolated preload boundary correctly. Native
paths are extracted from the real `File` objects during the capture phase and only
plain strings are exposed to React. Sources, new-chat attachments, and existing-chat
attachments consume the same single-use path store. One unreadable entry does not
discard other files in the drop, and consumed paths cannot leak into a later drop.

Locked-library authentication now reports passphrase failures beside the field instead
of only writing a technical message to the page-level Settings banner. The backend's
safe `invalid_vault_secret` response maps to “Incorrect passphrase. Try again.” The
field is linked to an accessible alert, retains the attempted value for correction,
clears the alert on edit, accepts Enter, and clears after a successful unlock.

Packaged chat logs also exposed a request-stream lifecycle bug. A legacy middleware
originally used to reserve an unfinished chat field still consumed the request body
and replayed the same `http.request` message indefinitely. After the field became
supported the middleware no longer enforced anything, but Starlette's disconnect
listener still received the replayed body and closed otherwise successful answers
before the terminal `done` event. The obsolete middleware has been removed. A new
full-ASGI regression sends a persisted chat request through the real middleware stack
and requires `meta`, `token`, and `done` plus a `completed` generation. The renderer
also reloads the durable timeline if a connection closes at the terminal boundary,
showing a saved or partial answer once instead of appending a false context-error
message.

Current local validation for this source delta is green: 100/100 additional backend
QA tests, including normal completion and client-disconnect persistence; desktop
TypeScript and 98/98 Electron behavior tests; three focused native-drop boundary
tests; two focused unlock contract tests; rendered wrong/correct-passphrase checks at
1440×900 with no final-state console errors; the production renderer build and
renderer security audit; Python compile checks; and diff hygiene. The package was not
rebuilt, by owner request.

## July 27 MCP, Tunnel, And Reliability Completion

The latest source completes the local ChatGPT MCP connection implementation and the
reliability remediation plan. MCP tool contracts, stdio transport, and backend
handlers are separated across `bridge_mcp_tools.py`, `bridge_mcp_stdio.py`, and
`bridge_mcp.py`. The transport enforces strict schemas, byte bounds, UTF-8 and Unicode
control safety, bounded per-class/global concurrency, cancellation, overload rejection,
graceful EOF, duplicate-ID rejection, safe backend-reset errors, and total serialized
output limits.

Electron now owns an encrypted, supervised outbound Secure MCP Tunnel lifecycle.
Credentials are replaced atomically through OS encryption; transient network failures
retry with bounded jitter while authentication, permission, and version failures stop
reconnect. Helper integrity rejects symlinks, the MCP child receives a minimal
environment and a loopback-only backend origin, and no desktop bearer token enters the
child. Permission edits rotate the scoped Bridge token and refresh an active tunnel.
Deleting an active vault first forgets the tunnel.

Bridge writes have separate attempted/completed audit events, including read-only and
scope denials, conflicts, replays, approvals, and successful captures. The numbered
ChatGPT setup flow reconstructs progress from durable client, scope, tunnel, and audit
state, detects a successful `list_clusters` verification, and explains the confirmed
write test and immediate revoke path with simple copy.

Latest source validation is clean:

- backend: 810 passed, 1 optional skip, 2 explicit scale deselections, 0 failed;
- desktop: TypeScript passed and 91/91 Electron tests passed;
- MCP Inspector 0.21.2: development stdio read-only and read/write passed;
- MCP soak: 1,000 calls, initialization 824.159 ms, `list_clusters` p95 86.93 ms,
  maximum 160.779 ms, and 0 MiB MCP RSS growth;
- Odin scale: 50,000 files, 68.3 MiB peak memory; the concurrent run took 160.824 s;
- product scale: 10,000 sources queried in 0.108 s;
- security: clean, interrupted, offline-at-rest, and 1,200-source encrypted-vault
  drills passed with zero plaintext marker hits and zero import failures;
- dependency audits: no known Python or production npm vulnerabilities;
- diff hygiene: passed with line-ending warnings only.

The existing installer predates these final source changes. The owner will perform the
package rebuild later, so all post-rebuild packaged Inspector, soak, runtime, UI,
startup, Odin launcher, install, and uninstall gates remain pending. Real ChatGPT
workspace and live OpenAI tunnel validation also remain external release gates.

## Current Architecture

Vault is RAG-only. Retrieval is authoritative for facts, citations, dates, names, numbers, and missing-evidence behavior. Chat and Bridge consume the same bounded retrieval-first packet contract. Clusters are retrieval scopes with cached summaries and glossaries, not trained experts.

Temporal memory uses append-only fact versions with immutable speaker/source provenance, citations, validity windows, and supersession links. Runtime adapter `temporal-ledger-v4` supports current and historical preferences, state histories, resolved relative action dates, conservative cross-session advice, and named-speaker attribution for imported dialogue. Preference memory selection and consolidation share the same conservative routing and topic scope, so bounded `favorite` facts stay on ordinary retrieval and topic misses inject no unrelated preferences. Users can review, correct, remove, and locally refresh extracted facts.

Odin indexes approved repository files without executing or modifying project code. It supports persisted `context` and `code` scopes, immutable snapshots, atomic retrieval activation, cancellable jobs, AST-based Tier A/B extraction, CLI CRUD/query commands, project-backed clusters, scoped chat, and a dedicated Projects workspace. Graph and tree results remain hidden unless requested.

## Current Product Status

| Area | State |
| --- | --- |
| Core RAG and cluster lifecycle | Complete for V1 scope |
| Shared chat/Bridge context contract | Complete |
| Temporal fact history and user controls | Extractor v3, runtime ledger v4, cited histories, resolved day-level actions, conservative synthesis routing, and local legacy backfill implemented |
| Lossless atomic memory | Compiler v9 is production-wired; optional loopback-only local semantic enrichment, separate provenance/staleness state, content-free coverage diagnostics, and conservative entity/category aliases are implemented; retrieval activation remains gated |
| Claim-first bounded evidence packing | Shared consolidated v1 semantics pass offline non-regression; paid accuracy promotion remains gated |
| Odin scoped project workflow | Complete for current scope |
| Odin AST extraction | Tree-sitter/Python AST based; Tier A/B corpus deterministic |
| Desktop project, task, source, settings, and health surfaces | Implemented |
| Public README and benchmark report | Updated with LongMemEval, LoCoMo, and Open RAG results and qualified comparisons |
| ColBERT late-interaction retrieval | Compressed 300K proof measured; scoped path remains experimental and not production-enabled |
| Windows installer and clean-machine proof | Historical development/test 0.1.9 lifecycle passed; owner-deferred rebuild, post-rebuild validation, signing, and account separation remain |
| ChatGPT MCP and Secure Tunnel | Source implementation complete; development Inspector, fault/security, and 1,000-call soak pass; rebuilt-package and real-workspace gates remain |
| UI refinement and distillation | July 24 audit fixes, July 26 frameless chrome/model onboarding, and July 27 resumable ChatGPT setup are implemented; broader accessibility and rebuilt-package visual validation remain |

## Recent Desktop And Onboarding Stabilization

- The Windows `BrowserWindow` is frameless. Vault renders one 32 px draggable title region with native-like minimize, maximize/restore, and close controls across the main app, onboarding, and startup-repair surfaces. IPC handlers operate only on the sending window, and interactive controls are explicitly excluded from drag regions.
- Managed-model recommendation loading is now an initial-load state instead of flashing during the 750 ms status poll.
- Model download UI follows the backend model row as the authoritative state. A completed install can no longer be masked by a stale renderer-side `downloading` fallback.
- The compact model-download notice shows a terminal installed/cancelled state briefly, fades after 1.8 seconds, and unmounts after 2.4 seconds. Settings and onboarding use the same behavior.
- The managed Qwen activation probe now disables thinking, uses `/no_think`, and allows 32 output tokens. This prevents the four-token health probe from spending its complete budget on hidden reasoning and then reporting an empty generation.
- These changes pass source/build, focused backend, Electron, rendered-browser, and interactive-control validation. The existing `test-0.1.9-Setup.exe` and `win-unpacked` artifacts were built before this July 26 source delta and must not be represented as containing it.

## Latest Benchmark Snapshot

| Benchmark | Best relevant result | Efficiency |
| --- | --- | --- |
| Open RAG full retrieval, 3,045 questions | 0.6404 section Hit@1; 0.9011 Hit@5; 0.9484 Hit@10; 0.9961 document Hit@10 | 1.0597 s mean / 1.0648 s P95 query latency |
| Open RAG frozen QA prefix, 500 questions | 83.8% Kimi / 73.6% GPT-5.4; 86.2% judge agreement | 2,672.1 reader prompt tokens/query; $1.9102 recorded component cost |
| LongMemEval-S typed-v1, 500 questions | 83.8% Kimi / 83.2% GPT-5.4 | 33,331.9 reader prompt tokens/query |
| LongMemEval-S claim-first 10K, 500 questions | 81.8% Kimi / 82.0% GPT-5.4 | 8,307.1 tokens/query; 0/500 over budget; $4.5111 evaluation cost |
| LongMemEval atomic-memory v9 readiness, two frozen 200-question development sets | 4/200 and 5/200 reference-verified safe activations; zero false-safe activations; readiness remains no-go | 100% source-unit coverage; expected mean prompts 8,283.92 and 8,303.97, both below claim-first controls; 0 reader/judge calls |
| LongMemEval API semantic-extraction smoke, 12 exposed recovery/control questions | Claim-first 6/12 vs facts-only 7/12 dual-judge correct; 3 wins, 2 losses; promotion failed | 120 sessions, 4,089 valid facts, $8.7551 extraction; 0/12 safe activations; facts-only prompts increased |
| Evolving-memory v3, 40 paired questions | 100% baseline and 100% production-path accuracy across four categories | Mean reader prompt fell 774.7 to 181.3 tokens (76.6%); uncached reader cost fell 69.7% |
| LoCoMo ColBERT, 1,540 questions | 0.7606 recall@10; 66.75% Kimi / 63.96% GPT-5.4 | 650.4 reader prompt tokens/query; $1.7388 evaluation cost |
| LoCoMo temporal activation audit, 34 frozen questions | Broad routing regressed Kimi by 14.71 points; conservative routing restored the exact baseline | 34/34 former false positives now abstain; 0 API calls in paired rerun |
| Compressed ColBERT scale, 300K items | 0.7303 recall@10 on 100 controlled global questions | 1.134 GiB; 0.539 s scoped P95 / 0.865 s global P95 |

Claim-first reduced LongMemEval reader prompt volume by **75.08%**, measured reader-plus-dual-judge cost by **66.39%**, and mean reader latency by **60.68%** versus typed-v1, with a 2.0-point Kimi and 1.2-point GPT accuracy tradeoff. At the same workload shape, 100 questions use about 0.83M instead of 3.33M reader prompt tokens. Local benchmark ingestion used zero billable extraction or embedding API tokens.

The shared claim-consolidation pass preserved 0.978767 answer-session recall, 0.492 literal containment, and 0/500 over-budget questions while reducing the offline mean estimate from 9,032.54 to 9,004.75 tokens. It formed a cross-session group on only 1/500 LongMemEval questions, so this is safety and efficiency evidence rather than an accuracy claim. The expanded provenance fixture passed 9/9 cases with perfect exact-claim and citation/source-retention checks.

The dedicated evolving-memory v3 suite freezes 40 questions—10 each for current preferences, preference history, state history, and relative-date actions—with long irrelevant-session distractors. Kimi K2.6 answered both the legacy and production arms at 40/40, confirmed independently by GPT-5.4 and deterministic required-fact checks. Production memory reduced mean prompt tokens by 76.6%, P95 prompt tokens by 65.0%, mean context characters by 78.8%, and estimated uncached reader cost by 69.7%. This validates the explicit fact families under controlled conditions; it is not a general LoCoMo or LongMemEval accuracy claim.

The first production-shaped LoCoMo temporal-memory run activated 34 preference-adjacent questions but reduced activation-slice F1 from 0.6008 to 0.5419, Kimi acceptance from 26/34 to 21/34, and GPT-5.4 acceptance from 22/34 to 21/34. It was rejected. Named-speaker routing now requires an explicit synthesis query, topic misses abstain, and fallback outputs are reused in paired experiments. The corrected frozen rerun changed 0/34 former false positives and exactly preserved all baseline scores at zero API cost. This closes the regression but does not establish a positive LoCoMo accuracy gain.

Atomic-memory v9 is the current LongMemEval development state. Production chat sync compiles every supported message into separate, queryable atomic fact and source-unit tables without flooding the curated temporal-fact index. The compiler types general explicit category counts, materializes conservative progressive totals, and records explicit named-entity category memberships such as doctor/physician aliases. Membership facts remain open-world and cannot independently satisfy a distinct-count closure contract. A forced offline replay changed eight packets in each frozen set but did not change safe activation: 4/200 and 5/200, with all nine results evidence-complete and reference-correct and zero false-safe activations. The preregistered 10% activation gate still fails, so reader and judge evaluation remains blocked.

`scripts/backend/inspect_atomic_memory_coverage.py` now performs backup-protected backfill and emits content-free per-vault measures for session coverage, user-turn fact yield, terminal source-unit coverage, closed cardinalities, and progressive counters. The configured database and the only packaged pre-vault database on the current machine both contain zero chat sessions, so no real-user activation/yield claim is available yet.

The main memory-quality constraint is no longer retrieval or packet budget. It is ingestion-time semantic closure: implicit singular counts, category membership, progressive totals, event identity, and supersession must be normalized before query time. LongMemEval cannot provide another meaningful final split under the current rules because only seven eligible untouched questions remain; both 200-question manifests are development-exposed.

These are benchmark measurements, not universal user-bill guarantees. Model pricing, caching, question complexity, answer length, and judge use change monetary cost. LongMemEval is now development-exposed, so future promotion claims require a preregistered untouched set or another benchmark.

Open RAG supplies that independent external-corpus check for document retrieval. Its complete 3,045-query retrieval result is strong, while the frozen first-500 QA gate exposes remaining multimodal section-selection and answer-judging variance. The 2,672.1 prompt tokens/query is the best measured Open RAG packet size, but it is not directly comparable to LongMemEval's 8,307.1 because the corpus and question shape differ. The paid QA run remains intentionally paused after 500 questions.

## Validation Snapshot

- Latest recorded backend suite: `810 passed`, `1 skipped`, `2 scale tests
  deselected`; one non-blocking Starlette TestClient compatibility warning
- Desktop TypeScript check and production client/SSR build: passed on the latest recorded product slice
- Electron behavior tests: `91 passed`
- Python and npm dependency audits: no known vulnerabilities in the pinned repository environments
- GitHub CI: current action majors, least-privilege read permission, dependency audit, desktop lint/build, four backend tiers, and manual Odin scale gate
- Published CI proof: run `30182242079` passed dependency audit, desktop, quick, integration, system, and benchmark jobs; the manual scale job was correctly skipped
- Odin 50,000-file discovery gate: `160.824 s`, `68.3 MiB` peak traced memory
  while the MCP Inspector ran concurrently; prior isolated result `95.777 s`
- MCP development Inspector: read-only and read/write profiles passed
- MCP source soak: 1,000 calls; `list_clusters` p95 `86.93 ms`; 0 MiB RSS growth
- Product metadata scale: 10,000 sources queried in `0.108 s`
- Latest source security drills: clean, interrupted, offline-at-rest, and 1,200-source
  encrypted vault all passed
- Project/task/evidence UI: passed at the 1024 px minimum against an isolated backend
- npm dependency audit: `0 vulnerabilities`
- Claim-packing CI gate enforces budget, answer-session recall, literal containment, and packet size
- Evolving-memory v3: 40/40 production answers accepted, with 0 scorer disagreements
- Frozen LoCoMo activation correction: exact baseline preservation on 34/34 former false positives with zero API calls
- Atomic-memory v7: two clean 200-question offline replays, 4 and 5 safe activations, zero false-safe activations, and no reader/judge calls
- Open RAG full retrieval: 3,045/3,045 completed; 0.9484 section Hit@10, 0.9961 document Hit@10, and 1.0597 s mean latency
- Open RAG paid QA gate: 500/500 completed with no length finishes; 83.8% Kimi, 73.6% GPT-5.4, and 86.2% judge agreement
- UI distillation browser audit: 46 TSX interaction checks passed; 13 routes rendered at 1440x900 and 768x900 plus the cluster route at 512 px without overflow, unlabeled controls, browser errors, or failed close/reset interactions
- July 26 desktop/model-onboarding delta: production desktop build passed; 57 Electron tests passed; managed-runtime tests passed 4/4; focused onboarding QA passed 2/2; interactive-control audit passed across 42 TSX files; rendered model-download transition completed with zero console errors

## Active Decisions And Boundaries

- Do not restore LoRA/expert runtime paths; the live product is RAG-only.
- Do not enable ColBERT as a universal production retriever. The 300K compressed proof supports an opt-in cluster-scoped path, but global fan-out failed the 850 ms P95 gate and lifecycle, memory, packaging/licensing, migration, deletion, concurrency, encryption, and cross-dataset behavior remain unresolved.
- Treat scoped/global recall equality as controlled synthetic evidence only; it does not prove that relevant cross-cluster evidence can be omitted. Keep a global dense/BM25 fallback in the design.
- Do not optimize only for exposed benchmark questions. Product changes must improve real retrieval, evidence provenance, temporal reasoning, or operating cost and pass regression gates.
- Reuse content-addressed retrieval, compilation, packet, reader, and judge artifacts; during development rerun only questions affected by the changed capability. Reserve full model evaluation for promotion candidates.
- Local model-backed benchmarks require the verified NVIDIA CUDA runtime and must fail rather than silently fall back to CPU. Deterministic parsing, JSON comparison, and contract checks remain CPU-only.
- Atomic-memory cache versions must change whenever write-time fact semantics or unit typing changes; coverage fingerprints alone cannot invalidate already-materialized fact objects.
- Keep benchmark question-family labels separate from root-cause analysis. A temporal question is not automatically a temporal-resolution failure.
- Consolidation must remain derived navigation metadata. Never discard, rewrite, or outrank its immutable cited source claims, and require at least two contributing sessions.
- Current preference/advice reduction must exclude superseded facts. Historical versions are admitted only for explicit change or history questions.
- Preference-adjacent words alone must not activate synthesis. Named-speaker routing requires an explicit aggregate preference request, and a topic miss must fall back without injecting unrelated facts.
- Benchmark reports are blocked while any reader response remains length-limited; fallback hypotheses and judgments must be reused in activation-only experiments so reader variance cannot masquerade as feature impact.
- Resolve event dates only at declared precision: safe day expressions may set completed-action event time, while coarse ranges remain metadata and never silently backdate current state.
- Keep resolved event dates and their verbatim relative citations as separate representations; model-facing evidence receives the resolved date while citation metadata retains the original wording to prevent double application.
- Keep ambiguous dynamic code relationships non-authoritative.
- Keep graphs request-only and project pages focused on status, questions, evidence, and activity.
- Missing local synthesis is a supported retrieval-draft fallback, not a retrieval failure.

## Immediate Next Steps

1. Extend ingestion-time atomic normalization for category membership, implicit singular entities, repeated-event/project identity, structured table relationships, progressive counters, and supersession chains; keep the zero-false-safe gate unchanged. The local Qwen3 pilot did not close categories, while the 12-question GPT-5.4 extraction smoke gained three answers but lost two controls and activated 0/12 safe contracts.
2. Raise safe atomic activation to at least 10% on both development sets before any reader/judge evaluation, then freeze a genuinely fresh corpus or benchmark split for promotion evidence.
3. Owner: rebuild and retest the 0.1.9 installer from the latest
   frameless-shell/model-onboarding/MCP source, then complete account-separation and
   signing proof. Rerun packaged Inspector, soak, runtime, UI, startup, Odin, install,
   and uninstall gates against that artifact.
4. Prototype bounded staging plus verified atomic compressed-shard rebuilds, with immediate tombstone filtering, runtime memory-pressure fallback, cross-cluster routing tests, encryption, exact artifact licensing, and a second real corpus before reconsidering ColBERT activation.
5. Create a fresh, preregistered memory-quality set with genuine distributed preference-synthesis, reversal, state-history, temporal-action, category-count, and cumulative-state cases.
6. Improve Odin TypeScript/React graph-to-prompt ranking and authoritative cross-file import/re-export/reference coverage, then rerun multi-model external evaluation.
7. Run the manual Odin scale workflow when the next discovery/indexing change needs promotion evidence.
8. Finish the remaining UI audit items: source-inspector persistence, stale embedded project/search/chat handlers, Bridge and Settings decomposition, keyboard/accessibility coverage, 200% zoom, offline/locked states, and rebuilt-package Electron validation.
9. Execute the seven credentialed ChatGPT/Secure MCP Tunnel release gates before
   broad rollout. These require an authorized workspace and live tunnel credentials.

## Canonical References

- Detailed internal state: `docs/OVERALL_CONTEXT.md`
- Public product overview: `ReadME.md`
- Public benchmark methodology and analysis: `BENCHMARK.md`
- UI implementation status and remaining backlog: `docs/UI_RECOMMENDATIONS_BACKLOG.md`
- Odin implementation: `backend/app/core/projects.py`, `backend/app/core/project_graph.py`, and `backend/app/api/routes/projects.py`
- Temporal memory implementation: `backend/app/core/claim_semantics.py`, `backend/app/core/temporal_facts.py`, and `backend/app/core/typed_evidence_runtime.py`
- Paired memory evaluation: `scripts/backend/evaluate_evolving_memory_api.py` and `scripts/backend/evaluate_locomo_temporal_paired.py`

## July 29 Deep-Audit Implementation Pass

The current deep-audit remediation is being delivered as product invariants,
not fixture-specific patches. Atomic cluster membership, transcript exclusion,
typed background-job failures, partial import recovery, adaptive metadata work,
durable chat generation, model recovery, whole-computer model discovery,
evidence-gated TurboVec activation, and unclustered-source retrieval are now in
source with focused checks.

Odin now treats project freshness as layered state. A normal Git sync reads only
committed-since-baseline, staged, unstaged, untracked non-ignored, deleted, and
renamed paths; unchanged sources and chunks remain stable. Retrieval can become
current while the prior structure snapshot remains explicitly stale. Large,
incomplete, non-Git, or baseline-less changes fall back deterministically to
the phased full path. Project answer contracts expose evidence roles, snapshot
identity, limitations, and currentness, and no longer imply authority without
implementation evidence.

Desktop validation also moved beyond static source checks. The window-control
no-go zone uses measured collision geometry and passed a rendered 1024×680
intersection check. The import-progress overlay was dragged across the viewport
in a live render; that test exposed and then verified a reload-position race.
The browser extension now keeps selection text out of page DOM and background
storage, verifies active-tab identity, restricts cleartext transport to
loopback, bounds uploads, and supports local token replacement.

Remaining release work is Settings and recovery decomposition, broader
accessibility/zoom/offline coverage, diagnostic-export verification, the final
full regression, and packaged-Electron validation. No installer has been
rebuilt during this pass.

The diagnostics contract has since moved to bundle format v2. Raw logs are no
longer included; the bundle contains bounded log-level and diagnostic-ID
summaries plus privacy-filtered runtime state. A focused upgrade test also
caught and fixed index-before-column ordering for pre-request-ID chat
generation tables. CI now explicitly gates extension behavior, renderer
security, interactive controls, rendered window geometry and popup dragging,
Ruff, compilation, and optional packaged release-candidate smoke.

Settings refresh work is now scoped to the visible section. In particular,
timer-based Settings refresh can no longer launch a whole-computer model scan;
discovery begins only after the user opens model management and chooses
**Scan this computer**. Rendered recovery tests now cover wrong passphrases,
focus restoration, model-unavailable notification, 200% text, reduced motion,
minimum viewport geometry, and draggable import persistence. Source-folder
group queries are server-filtered and bounded with pagination metadata.

Source descriptions now have a progressive quality contract. Indexing writes a
fast deterministic description and keywords immediately, so search and initial
organization never wait for the chat model. A durable low-priority semantic job
then improves the description when the local model is available, rechecks the
source content hash before publication, and refreshes affected cluster
metadata. The source inspector labels this temporary state **Improving**.
Migration 25 persists quality, semantic version, and update time; focused
migration, content-preservation, model-loss/resume, and desktop type checks
cover the path.

Direct Odin use during the pass also exposed an executable-approval drift
failure after the local CLI changed. The security binding remains intact, but
the CLI now returns a clear repair-and-pair explanation plus stable
`executable_fingerprint_mismatch` and `next_action: repair_and_pair` fields.
The active plan adds a single idempotent Settings repair flow, an Odin doctor
contract, and a bounded project Changes inbox backed by the delta probe rather
than a full tree re-index.

Focused validation for this pass is green: four targeted metadata/migration/Odin
backend tests and the semantic model-loss/resume test passed; desktop
typechecking and 148 Electron behavior tests passed; all six rendered
Playwright flows passed; and the 24 extension tests plus renderer, control, and
lockfile audits passed. Python compilation passed. Ruff is not installed in
the current local virtual environment and remains an explicit CI/final
environment gate.

The subsequent UI inefficiency sweep removed the last browser-native
confirmations: library relocation and reversible cluster merge now use Vault's
accessible confirmation component. It also replaced the cluster detail route's
full-vault destination walk with escaped server search and a 50-item result
window for move and merge. Focused backend, behavior, and TypeScript checks
passed.

`odin doctor` is now available as a content-free diagnostic. It checks the
launcher, local Vault runtime descriptor, and executable approval, then returns
stable status, error code, and next action fields. Running it against the
current development launcher correctly identified executable approval drift
and recommended `repair_and_pair`; two focused trust/doctor tests passed.
