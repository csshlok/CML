# Overall Context

## 2026-07-30 — answer policy, cluster lifecycle, and queue throughput

Chat now separates routing from answer generation instead of treating retrieval as
the answer. General questions go directly to the selected model. Questions about
saved material receive a bounded context packet and one of four model-agnostic
policies: normal grounded synthesis for sufficient evidence, qualified reasoning
for weak but relevant evidence, an explicit side-by-side conflict explanation for
contradictory evidence, and extract/refuse behavior for unsafe or hostile evidence.
The same guard is enforced for streaming and non-streaming responses. Prompt
guidance makes source text evidence rather than instructions, while still allowing
locally connected models to reason instead of returning a mechanical extract.

Trusted profile fields are available to identity questions through a small
profile-aware packet. Generic assistant refusals and the current conversation's
assistant output are not promoted into authoritative personal memory. Answer
diagnostics record the selected policy mode, so direct, qualified, conflict,
grounded, and extraction behavior can be inspected without coupling the pipeline
to one model family.

Cluster maintenance is scoped to the active vault's durable cluster records rather
than stale or source-level rows, so task progress no longer reports thousands of
nonexistent clusters. Ready sources are reconciled with cluster membership and can
remain conservatively unclustered when placement evidence is insufficient. Users
can create a cluster, move ready or unclustered documents into it from Sources,
move documents between clusters, and delete clusters. Empty chat clusters are
cleaned up after their final chat is removed.

Semantic enrichment finalizes source work independently and coalesces cluster
profile refresh into bounded work after an enrichment wave. This removes the
per-source refresh amplification that left large imports with long extraction
queues. Adaptive scheduling, visible import controls, failed-source recovery,
encrypted-source handling, and task reporting share the corrected lifecycle.

Projects now report freshness against Odin's active indexed snapshot rather than
raw Git HEAD alone. Working-tree changes already represented by the active
snapshot do not become false “details unavailable” or unsynchronized warnings.
Project details and Odin synchronization use the same snapshot semantics.

Desktop chat renders supported inline Markdown such as `**bold**` instead of
showing delimiters. The associated source changes were verified in focused
batches: the answer-policy and route batch passed 39 tests plus 3 subtests,
semantic batching passed 6 focused tests, chat presentation passed 5 Node tests
and TypeScript checking, and the focused rendered Markdown check passed. A full
regression run and a new Windows release artifact remain explicit promotion steps
and have not been claimed for this source state.

Last updated: 2026-07-30

## 2026-07-29 — deep audit implementation

The latest cross-layer review found that project indexing activation updated source membership but not chunk membership. This produced a misleading state: the UI and Odin correctly showed the selected project while retrieval returned no evidence. Activation and migration 16 now enforce and repair that invariant, with focused Odin and chat retrieval tests.

Graph requests now use a clean, on-demand project-map page rather than embedding a dense fixed-size graph in chat. Both project and knowledge maps support progressive expansion; selected details remain closed by default. Project graph responses include traceable orientation data—key areas, relationship counts, connected components, and observed directed flows—so the UI and Odin exports can explain what a view represents.

The review also bounded a quadratic knowledge-map edge path, restored primary project-cluster relationships, and restricted renderer runtime backend URLs to local loopback origins. The approved follow-up is now implemented in source: persisted cluster candidate profiles, evidence-stable move decisions, conservative placement, bounded chat hydration, Odin client pagination, legacy project-job migration, one project activation writer, and a stable public error boundary. The local audit and fix-plan files are intentionally ignored rather than retained as tracked product documentation.

Last updated: 2026-07-29

This file preserves the longer-form current state behind `docs/PROJECT_CONTEXT.md`. It should hold durable background, validation summaries, and high-signal historical notes, not stale architecture claims.

## July 29 Bounded Data Paths And Global Window Safety

The desktop shell publishes one upper-right control geometry contract: 138 pixels
for the three controls, 32 pixels high, plus a 12-pixel interaction buffer. The
safe rectangle is transparent and does not reserve a full-width strip. Chat and
every primary route header consume the contract, while static startup and repair
documents use the same numeric tokens. Source tests reject the retired
`desktop-window-action` and chat-only clearance classes. A rendered collision pass
at 1536x960 and 1024x768 found no intersecting interactive controls across Home,
Sources, Clusters, Chat, Projects, Map, Search, Tasks, Timeline, Bridge, Settings,
onboarding, and the not-found route. Console errors in that isolated browser pass
were expected connection refusals because no backend was started.

Schema version 18 adds versioned cluster candidate profiles and evidence keys for
move decisions. Candidate retrieval uses an indexed lexical shortlist capped at 32
profiles; suggestion review reads at most 240 eligible sources and only their
active vectors. Project-linked sources and clusters are excluded. New standalone
sources require a high absolute score, a clear margin, and acceptable cohesion for
automatic placement; otherwise they remain unclustered. Existing sources are never
silently moved. Accept and dismiss decisions remain stable until the source
checksum or candidate profile membership/version changes.

Cluster identity publication uses representative source summaries, source types,
weighted terms, a centroid, cohesion, and a deterministic membership hash. Manual
names and descriptions remain protected. A durable organization backfill removes
abandoned automatic clusters and refreshes stale profiles in 20-cluster work units.
Its task reports progress and failures and supports pause, resume, and cancellation.

Chat now separates metadata from a unified message/retriable-generation timeline.
The desktop reads the newest 80 items, prepends older cursor pages while preserving
scroll position, and polls only newer deltas for active work. Stable IDs reconcile
optimistic messages without replacing the conversation. Tests cover 2,000 messages,
a new message arriving after the initial page, and an older cursor whose boundary
row was removed by retention.

Odin Settings reads active connections and pending approvals without loading
history. Revoked and rotated clients are fetched only after Connection history is
opened and continue through cursor pages. The displayed active count comes from an
exact indexed count. A 1,000-client fixture confirms bounded pages.

The retired monolithic project indexer and activation helper are removed.
Startup migration marks historical `project_index` jobs failed with a clear reason
and queues the four phased jobs for the affected project. The phased pipeline keeps
the extractor-version contract and remains the only active snapshot writer.

HTTP, validation, and chat-stream failures now return stable codes, simple copy,
optional action text, and a diagnostic ID. Original exceptions are logged locally.
Raw paths, request payload details, OS messages, and stack information do not cross
the public response boundary.

The completed verification pass collected 870 backend tests: 868 passed. The Odin
release scale case remains explicitly opt-in, and the TurboVec benchmark was
skipped because that optional runtime is not installed. All 141 Electron behavior
tests passed, as did TypeScript checking, the production renderer build, Python
bytecode compilation, the renderer HTML safety audit, the 45-file interactive
control audit, the package layout and helper-manifest audit, and Git's whitespace
check. Rendered desktop-safe-zone checks at 1536x960 and 1024x768 found no
interactive overlap on the primary application, onboarding, or error routes.

## July 29 Direct Projects, Observable Indexing, And Folder Browsing

The desktop Projects route and Odin now share the same project registration and
snapshot behavior. Users can select project folders from Projects without first
installing or pairing the CLI; terminal users can continue to register, synchronize,
and query the same records with Odin. Project cluster descriptions and run trigger
labels no longer claim that Odin was the entry point when the desktop performed the
registration.

The reported CML indexing stall was diagnosed against the live project database.
Discovery and structure completed normally, but retrieval processed 566 files in a
single SQLite transaction for roughly fifteen minutes. Its heartbeat writes were
therefore invisible until commit, while the activation job correctly waited on the
retrieval dependency. Retrieval now selects only unfinished rows and commits
12-file batches. The stage is restart-safe, cancellation is checked between
batches, and completed/total progress becomes visible after every commit.
Dependency copy now describes what the user is waiting for rather than displaying
an internal scheduler status.

Candidate project sources remain isolated from all default source lists, counts,
type totals, cluster totals, and latest-source summaries. This preserves atomic
snapshot activation and prevents hundreds of staging rows from appearing as
unclustered sources. Once active, projects with at least 20 sources are represented
as folder rows in Sources. The durable batch-import payload also records selected
folder roots; roots containing at least 20 imported files become the same kind of
folder row. Opening either folder type scopes the normal source list, filters,
pagination, inspector, reindex, open, and delete actions to that folder.

Locked libraries now provide an inline passphrase form with local error feedback.
The Privacy route is reserved for reset and recovery. Ctrl+L and the command palette
both invoke the backend lock authority for the current secured vault and immediately
clear the open workspace.

## July 29 Cross-Workflow Reliability And Odin Installation

This pass addressed a connected set of discoverability, durability, and truthful
state problems rather than treating each screenshot as an isolated UI defect.

Suggested cluster moves now have a durable decision record keyed to the source and
suggested destination. An accepted suggestion updates the source's cluster in the
backend before the interface removes the row; a dismissed suggestion remains
suppressed until the underlying source changes. Suggestions appear in the default
Focused Home layout, the Clusters navigation item shows their count, and unseen
suggestions create a small bottom-of-frame notification. Automatic cluster identity
now records whether its name came from Vault or the user, allowing ingestion to
improve weak automatic names and summaries without replacing explicit user edits.

Chat generation state is durable across navigation. Leaving a chat no longer aborts
its request, conversation history marks sessions with active generations, and a
global poll reports newly completed answers when the user is elsewhere. Reopening
an active chat reconnects to its generation state, while a prematurely closed
response stream checks for the durable saved answer before showing an interruption.
Attachments are hydrated from `chat_attachments` and rendered as decoded filename
chips; legacy `Attachments:` prompt lines remain readable without being displayed
as message copy. Successful generation now synchronizes chat temporal facts
immediately, so Settings Memory history advances after completed conversations
instead of depending on startup or backfill.

Ingestion visibility is shared across routes. Sources includes type and status
filters, the floating import surface retains all failed filenames and reasons, and
Tasks exposes the same per-file result from the durable job payload. Import notices
remain dismissible without cancelling work and preserve pause, resume, and
confirmed stop behavior. Tasks gained an explicit refresh action. Task, Timeline,
and source details remain closed until a row is selected and can be closed again.
Source list responses now decrypt available summaries, and ingestion-generated
summaries feed source descriptions, previews, cluster profiles, representative
summaries, and automatic cluster names.

Settings now presents temporal memory as direct information under its heading and
removes the redundant diagnostic box. The old Local imports surface was a reader
for integration-import rows but had no creation path, so normal users could not
activate it. It is now Folder sync: Add folder uses the native picker, creates the
integration import, and starts reconciliation. Model management similarly uses
progressive disclosure. The full list stays hidden until requested, compatibility
language matches actual chat eligibility, and recommendation evidence distinguishes
measurements, catalog estimates, metadata, and unavailable evidence. Catalog
fallbacks carry bounded confidence and a lower score than direct measurements.

The Odin installer previously assumed Electron could always resolve
`app.getPath("localAppData")`, which is not a supported Electron path name and caused
installation to fail before the launcher could be written. The Vault-managed
installer now resolves a writable Odin bin directory from Windows local application
data, application data, Electron user data, or the user profile, creates the
launcher atomically, updates the user `PATH`, and verifies `odin --help`. Pairing
uses a detached visible PowerShell process instead of a blocking command-shell
handoff, so Settings remains responsive while the user approves access.

Settings also exposes **Install with uv** for users who manage Python command-line
tools with Astral uv. Vault runs `uv tool install` against the packaged backend,
keeps dependencies isolated, locates the resulting tool bin, and verifies the Odin
command before reporting success. Installation and authorization remain separate:
either launcher must still complete `odin auth pair`, and approved clients remain
rotatable or revocable. The Projects settings surface can select a repository on
the current computer and register it through Vault; local project registration,
snapshot activation, synchronization, scope changes, failure isolation, and
removal are covered by the Odin backend suite.

Validation evidence:

| Gate | Result |
| --- | --- |
| Desktop TypeScript and behavior | Passed; 128/128 Electron tests |
| Backend | Passed; 837 tests, two environment-dependent skips |
| Focused chat, cluster, recommendation, and Odin regressions | Passed |
| Production renderer | Built successfully |
| Python compilation | Passed |
| Renderer HTML safety | Passed |
| Interactive-control audit | Passed across 43 TSX files |
| Diff hygiene | Passed; line-ending notices only |
| Windows package rebuild | Not run by request |

The full backend collection has one additional existing packaging-contract failure:
`backend/bin/ocr/README.md` is deleted in the current dirty worktree. That unrelated
deletion was preserved rather than silently restored, and its single contract test
was deselected for the clean implementation validation.

## July 29 Qwen Runtime Throughput Repair

The approximately 5 token/second Qwen3-4B result was reproduced as an architectural
packaging problem rather than a model defect. The release script staged only
`llama-b9374-bin-win-cpu-x64.zip`, and the managed supervisor supplied neither a
GPU-offload policy nor explicit generation and batch thread counts. Repeated starts
had also left CPU llama-server processes alive after their parent backend exited,
increasing RAM and CPU pressure.

The Windows package contract now contains two independently pinned and verified
llama.cpp b9374 runtimes:

- CPU: `llama-b9374-bin-win-cpu-x64.zip`
- NVIDIA: `llama-b9374-bin-win-cuda-12.4-x64.zip` plus its matching CUDA runtime
  archive

The CPU executable remains at `llm-runtime/llama-server.exe` for compatibility.
The CUDA executable and its CUBLAS/CUDART dependencies live under
`llm-runtime/cuda/`. Electron supplies both paths to the backend. On a dedicated
NVIDIA GPU with at least 3 GiB usable VRAM, the supervisor attempts CUDA first with
automatic GPU-layer fitting and then attempts CPU if startup or generation probing
fails. CPU-only and unsupported systems continue to use the existing executable.
The runtime records the selected backend, failed attempts, and stale-process cleanup
result for diagnostics.

Process cleanup deliberately fails closed. A process is eligible only when its
normalized executable path is one of Vault's exact staged runtimes, its `--model`
value is the selected or previously selected GGUF path, and its `--host` value is
loopback. Surviving processes cause activation to stop with a clear error. Windows
package output cleanup similarly stops only executables whose resolved paths are
inside the explicit output directory, then retries locked-directory removal.

Live validation used the staged CUDA runtime and the affected
Qwen3-4B-Q4_K_M model on an i7-12700H and RTX 3060 Laptop GPU. With a 4096-token
context, 14 generation threads, 20 batch threads, and automatic offload, llama.cpp
reported 76.03 prompt tokens/second and 38.75 generated tokens/second for 25 output
tokens, using 3583 MiB VRAM. This is about 7.7 times the observed packaged
throughput. The benchmark server was stopped after the measurement.

Validation passed:

- 9 focused managed-runtime tests, including CUDA preference, CPU fallback,
  command tuning, exact orphan matching, and fail-closed survivors;
- 416 selected backend tests and the focused model-recommender suite;
- all Electron behavior tests, desktop TypeScript, and production renderer build;
- renderer HTML safety, interactive-control, and package-layout security audits;
- PowerShell parse checks, Python compile checks, and diff hygiene.

No Windows package was built. The next owner-run build must repeat clean-machine
layout, packaged backend/runtime, full-vault, app-launch, installer, and uninstall
checks. The self-contained CUDA libraries add roughly 1.2 GiB to the unpacked
payload before compression, so release storage and download-size review remains a
shipping gate.

## July 28 0.1.11 Integration And Release Hardening

PR #5, `Fix grounded RAG, Odin pairing, and release reliability`, was merged into
`main` at merge commit `5f04b90dca7625ebf16ef4833ba16abb2bc29088` after all
hosted checks passed. Local review passed desktop TypeScript and 125 Electron
behavior tests plus the focused Odin authentication suite. One model-download test
failed only in a clean worktree because it used the host's nearly full C: temp
drive for a real multi-gigabyte preflight; the test now mocks that unrelated
preflight and verifies the concurrency behavior deterministically.

Before the release bump, three additional edge cases were closed:

- pairing-list refresh remains read-only but now filters and limits inside SQLite
  instead of materializing every historical pairing request;
- the installed Odin launcher passes its command path through an environment
  variable, so a Windows user or installation path containing an apostrophe cannot
  break the PowerShell handoff;
- the Odin launcher contract version advanced so existing launchers are repaired
  on the next install/status flow.

Focused follow-up validation passed all nine Odin launcher tests and eleven
pairing/model-download backend tests. Repository version metadata is `0.1.11`.
Packaging and release artifact creation are intentionally pending the owner-run
Windows rebuild.

## July 28 Packaged Preload Failure And Static Recovery Shell

The failing 0.1.10 unpacked runtime log identified the direct packaged-app cause:
`preload.cjs` could not resolve `./dropped-files.cjs` from the sandbox bundle.
Electron limits `require` inside a sandboxed preload, so the failure occurred before
Vault exposed its desktop API. The HTTP renderer loaded, but it could not emit
`cml:renderer-ready`; ten seconds later the main process replaced it with the repair
screen. Because the same missing bridge backed minimize, maximize, close, retry,
copy, native drop paths, and other desktop actions, the apparent UI failures shared
one architectural cause.

The small dropped-file capture and readable-IPC-error helpers are now embedded in
the preload entry. This preserves the sandbox and avoids weakening Electron's
security model. A source-level packaging regression test requires the sandboxed
preload to have no relative `require` calls.

Startup and recovery chrome is now a static shared shell:

- `startup.html` renders the same 44 px three-button control group used by recovery.
- `repair.html` replaces dynamic `data:` recovery documents and loads through
  `BrowserWindow.loadFile`, allowing the packaged preload to run normally.
- Dynamic diagnostics are serialized as a query state object and inserted only with
  `textContent`; no backend error text becomes markup.
- Retry, copy, open-anyway, and close use external event listeners under a
  restrictive local-file CSP and report failure instead of silently doing nothing.
- Window glyphs are drawn with CSS, avoiding Unicode/font corruption in packaged
  builds, and maximize/restore state follows the main-process state event.

Validation evidence for this unbuilt source delta:

| Gate | Result |
| --- | --- |
| Runtime evidence | Confirmed sandbox preload rejection and missing readiness signal in the packaged desktop log |
| Desktop behavior | TypeScript and 118/118 Electron tests passed |
| Preload packaging regression | Passed; no relative imports remain in `preload.cjs` |
| Production renderer | Built successfully |
| Static startup and repair rendering | Controls visible at 1280×820; wordmark and action hierarchy verified |
| Rebuilt Windows package | Pending owner rebuild |

## July 28 Unified Error Branding And Recovery Language

The dedicated error paths previously diverged even after the opening-library screen
was corrected. The React not-found and error boundaries had no brand mark, the
server-render fallback used generic centered copy, the favicon and dormant
`BrandLogo` icon variant still referenced the legacy `logo.svg`, and the
last-resort startup HTML embedded a second old mark. Repair pages also exposed terms
such as renderer, packaged UI, backend readiness, schema state, and database health
as primary user copy.

The canonical `Container.svg` opening-library wordmark now drives `BrandLogo`, the
favicon, startup, repair, route errors, and server-render errors. Legacy
`logo.svg` and application references to the README-only `Frame 8.png` asset were deleted. The large embedded startup
artwork was removed from the Electron main process. A missing startup document now
routes through the packaged branded repair page; a tiny text-only page is reserved
for the more severe case where both startup and repair documents are absent.

Recovery screens now say that Vault or the current page could not open, then present
Try again and Return home/Close Vault actions. Package and service terminology is
kept out of the primary message. Exact phase, backend or renderer errors, database
paths, and log locations remain in the structured diagnostic text copied by the
user. Integrity, schema-update, and library-lock cases retain distinct safe guidance
without promising automated repair.

Focused branding, startup fallback, Electron recovery, Home-brand consistency, and
window-control tests pass (56/56), as does the complete 122-test Electron run.
Desktop TypeScript, the renderer HTML safety audit, interactive-control audit,
production renderer build, and diff hygiene also pass. A 1280x820 rendered recovery
check confirmed the new wordmark, hierarchy, readable copy, and visible window
controls. The Windows package remains intentionally unbuilt pending the
owner-managed rebuild.

## July 28 Working-Overview Home And Cross-App Decluttering

The previous Home split similar recency and navigation actions across clusters,
recent sources, inbox, and activity, giving all of them equivalent visual weight.
It also fetched a small arbitrary cluster slice and had no durable user control over
the composition. Home now treats those surfaces as sections in a versioned
preference model. The recommended Focused order is Ask Vault, conditional Needs
attention, Continue working, Active clusters, and Quick actions. Library and
Activity presets recompose the same system for browsing or operational monitoring.

Ask Vault remains the dominant action and can target the entire vault or one cluster.
Needs attention does not render when there is no work; it derives direct links for
failed sources, unsorted sources, paused or failed tasks, and local-service issues.
Continue working combines source, chat, cluster, and project activity. Active
clusters are ordered by the selected Home sort and display source count, indexing
state, and latest update rather than taking the first four backend rows. Type
filtering covers documents, notes, links, media, and code; sorting covers updated,
added, alphabetical, and attention-first modes.

Customize uses a Radix popover rather than a modal. It provides Focused, Library,
and Activity presets; comfortable or compact density; list or grid presentation;
section switches; up/down ordering controls with accessible names; and reset. The
header and reset footer stay fixed while the section list scrolls inside a
viewport-bounded panel. This addresses a rendered 800 px-height failure in which
Reset was initially outside the click viewport. Preferences are normalized against
known enum and section values before read or write. Hidden-section normalization is
separate from order normalization so a valid empty hidden list remains “show all”
instead of being expanded to “hide all.” Each active vault ID namespaces its local
preference key, preventing settings from leaking between profiles/libraries.

The Home overview remains server-bounded. It requests limited source, activity,
chat, project, and cluster lists in parallel and uses grouped count APIs for totals.
The new `/sources/counts-by-type` endpoint performs one indexed aggregate query and
excludes tombstoned sources, avoiding one HTTP count request per type. `created_at`
now reaches the renderer domain model so Recently added is distinct from Recently
updated.

The same pass distilled nearby shared UI. Sidebar branding explicitly uses the
opening-library `Container.svg` wordmark; saved chats and cluster shortcuts share a
single Recent group with three entries of each type. Small tracked uppercase shared
labels and decorative cluster side stripes were removed. Settings no longer repeats
storage placeholders, active-model explanations, destructive-action consequences,
or library-protection state. Essential protection coverage is available immediately
below the Library unlock heading in a disclosure, while status copy is reduced to
Unlocked, Locked, or Not protected. Odin usage help and memory-correction behavior
also sit under their headings, with technical paths disclosed only on demand.

Validation evidence for this unbuilt source delta:

| Gate | Result |
| --- | --- |
| Home preference and presentation regressions | 5/5 passed, including profile-scoped persistence and invalid-state recovery |
| Complete desktop behavior run | TypeScript and 118/118 Electron tests passed |
| Focused backend scale/count tests | 3/3 passed |
| Python compilation and diff hygiene | Passed |
| Production renderer build | Passed |
| Rendered desktop Home | Focused and Library presets, Customize, reorder controls, and Reset passed at 1280x800 |
| Rendered compact Home | Header, controls, primary composer, and flat sections passed at 760x760 |
| Rendered console | Only expected `127.0.0.1:7343` connection refusals in the web-only harness |
| Rebuilt Windows package | Pending owner rebuild |

## July 28 Compact Window-Control Exclusion

The frameless desktop keeps its invisible top drag behavior; no full-width titlebar
row is reserved. The three Windows buttons remain 138×32 px at the upper-right, and
their transparent chrome container is now 150×44 px. The extra 12 px at the left and
bottom is intentionally inert so nearby application actions cannot lead directly
into a minimize or maximize hit target.

Only action groups that can occupy the upper-right use
`desktop-window-action`. Inside the Electron frame and above the desktop breakpoint,
that utility reserves the same 150 px horizontally. It is applied to Search, Home,
Sources inbox, Map, Projects, Tasks, Bridge, and Clusters. This avoids route-specific
magic numbers while preserving each page's original y-position, the invisible
titlebar, and the unmodified web layout. In the compact application header, the
brand remains centered and the service-status label reserves the same right-side
zone instead of appearing beneath the Windows buttons. Rendered checks confirmed
that route content still begins at y=0, Manage sources ends before the no-go area,
compact actions stay below the controls, and Search → Sources navigation remains
clickable. The 113-test desktop run, TypeScript, production web build, and
interactive-control audit pass.

## July 28 Durable File Imports And On-Demand Source Details

The Sources route previously launched up to four direct `from-path` requests and
stored only a short local message such as “Importing 20 files.” Leaving the route
unmounted the owner of that work and removed all feedback even though backend
requests could still be running. There was no persisted batch identity, aggregate
progress, pause, resume, or safe stop boundary.

File and folder selections now create one `source_import_batch` application job. Its
payload is bounded to 10,000 absolute paths and duplicate paths are removed while
preserving order. A partial unique index and an API-level check allow one queued,
running, or paused batch per vault. The worker keeps the established maximum of four
concurrent file operations, records every completed index plus created, updated, and
failed counts after each work unit, and resumes only unconfirmed indices after a
pause or backend restart. Individual file failures are contained rather than failing
the whole batch. The displayed failure list is capped at 100 entries and stores file
names and safe errors, not full filesystem paths.

Pause changes the durable job state immediately and prevents replacement work from
being scheduled; files already active are allowed to finish before the worker
releases the job. Resume returns the same job to the queue. Stop uses the existing
cooperative cancellation contract: queued or paused work is cancelled immediately,
while a running batch finishes already-active files and then acknowledges
cancellation. The UI explains this boundary in a confirmation dialog rather than
implying unsafe mid-parser termination. Paused jobs are included in queue counts,
task filters, cancellation rules, recovery behavior, and the sidebar task count.

The application route now owns a shared import-progress controller. It polls the
durable job, publishes terminal source-change events, and renders a compact,
dismissible progress surface fixed to the user's frame. Sources consumes the same
state for its inline bar. Both show processed/total files, integer percentage,
current file, failures, and folder-scan truncation. Pause, resume, and stop remain
available after navigation. Dismissing the global surface changes only its
visibility; it does not mutate or stop the job.

Sources previously always reserved a 326 px inspector track and rendered “Select a
source to inspect it” in the empty panel. The grid now defaults to
`minmax(0, 1fr) 0`, mounts the inspector only after row activation, transitions the
track to 326 px over 200 ms, and restores the full content width through an explicit
close control. Reduced-motion users receive an immediate state change. The 900 px
layout remains one column.

Validation evidence for this unbuilt source delta:

| Gate | Result |
| --- | --- |
| Focused source-import backend tests | 4/4 passed, including active pause/resume and duplicate-batch protection |
| Focused scheduler plus import tests | 16/16 passed |
| Focused desktop contracts | 3/3 passed |
| Complete desktop behavior run | 113/113 passed |
| Quick backend tier | 407/407 selected tests passed |
| Desktop TypeScript and production web build | Passed |
| Renderer HTML safety and interactive-control audit | Passed |
| Python compilation | Passed |
| Rendered import controls | Counts, percentage, progress, pause/resume, confirmed stop, and dismissal passed |
| Rendered persistence | Progress remained available after Sources → Tasks navigation |
| Rendered source inspector | Zero-width default and 326 px selected track passed at 1440×900; narrow layout passed at 900×800 |
| Console | 0 warnings and 0 errors after mocked reload |
| Real vault mutation | None; rendered API calls were intercepted |
| Rebuilt Windows package | Pending owner rebuild |

## July 28 Frame Notifications And Single-Source Cluster Moves

Settings previously rendered operation results in a full-width message above its
content. That feedback moved when the document scrolled, displaced the page, and
could be far from the control that initiated an action. Settings now publishes to
the notification system already mounted at the application root. The viewport is
fixed to the bottom center of the user's visible frame with pointer events limited
to each compact notification. Notices begin fading at 5,000 ms and are removed at
5,500 ms, honor reduced-motion preferences, remain manually dismissible, and keep
the existing status live region. The bottom-center placement also avoids the
bottom-right model-download status surface.

Settings refreshes service state every six seconds. Routing its previous polling
banner directly to notifications would therefore have created an endless sequence
of identical toasts during an outage. Poll-generated notices are deduplicated until
the underlying message changes or a complete Settings load succeeds; direct user
actions still produce feedback on every attempt. Rendered validation confirmed the
toast remains attached to the window rather than the page and is absent after 6.2
seconds.

Cluster merging already combined every source in two clusters, but there was no
direct way to correct one misplaced source. The cluster Sources tab now provides a
row-level Move action. Its dialog lists peer clusters in the same vault, excludes the
current cluster, disables the action when no destination exists, and keeps failures
inline so auto-expiring notifications cannot hide a blocked operation. Source title
navigation and the row action are separate interactive elements rather than an
invalid nested button inside a link.

The move deliberately reuses `PATCH /api/v1/sources/{id}` instead of introducing a
second membership mechanism. The source table has one authoritative `cluster_id`;
the backend checks that the destination belongs to the same vault, updates that
single value transactionally, invalidates relevant caches, queues summary refreshes
for both clusters, and reindexes an already indexed source. The UI requires the
returned `cluster_id` to match the requested destination before removing the row.
This prevents optimistic UI drift when a request is rejected or a stale service
responds unexpectedly. Destination discovery follows the backend's stable cursor
pages in 200-row batches and rejects a repeated cursor, so libraries with more than
1,000 clusters remain complete without risking an infinite pagination loop.

Validation evidence for this unbuilt source delta:

| Gate | Result |
| --- | --- |
| Focused source-move backend tests | 2/2 passed, including cross-vault rejection |
| Focused notification and move Electron tests | 6/6 passed |
| Complete desktop behavior run | TypeScript and 110/110 Electron tests passed |
| Quick backend tier | 403/403 selected tests passed; 417 slow/optional cases deselected by tier |
| Production build and renderer audits | Build, HTML safety, and 42-file interactive-control audit passed |
| Rendered Settings notification | Fixed-frame placement, expiry, and polling deduplication passed |
| Rendered source move | Desktop and 900x800 checks passed with mocked API; 0 console warnings/errors |
| Real vault mutation | None; rendered requests were intercepted |
| Rebuilt Windows package | Pending owner rebuild |

## July 28 Settings Section Deduplication

Settings used `showSection("library", "advanced")` for two complete cards. This made
Local imports and Evidence retention appear unchanged in both destinations and left
users without a clear mental model of where those controls belonged. The duplication
was presentation-only—the cards still operated on the same state and backend
actions—but it made the navigation look unfinished.

Local imports now belongs only to Library & security, alongside storage, memory
history, and library protection. Evidence retention now belongs only to Advanced,
alongside diagnostics and destructive maintenance. A source-level regression rejects
multi-section card conditions and asserts both canonical homes.

Rendered Playwright checks followed both desktop navigation buttons and the
narrow-width section selector. Each destination contained one expected card and none
of the other. The web-only harness reported expected backend 401 responses because it
does not have Electron's local API token; it produced no framework overlay or
renderer exception.

| Gate | Result |
| --- | --- |
| Focused Settings information-architecture tests | 2/2 passed |
| Desktop | TypeScript passed; 104/104 Electron tests passed |
| Production renderer build | Passed |
| Renderer HTML safety and interactive controls | Passed |
| Rendered Settings navigation | Passed at 1280×720 and 900×800 |

## July 28 Odin Launcher Path Repair

The Settings action for installing Odin failed with `Failed to get 'localAppData'
path`. Electron's `app.getPath` API does not define a `localAppData` key, so both the
launcher status probe and install handler failed while constructing configuration,
before atomic launcher creation, PATH registration, or the bounded `odin --help`
verification could run.

The launcher now resolves its per-user bin directory from the absolute
`LOCALAPPDATA` environment value and falls back to Electron's supported `appData`
path. On normal Windows layouts the fallback maps
`...\AppData\Roaming` to sibling `...\AppData\Local`, preserving the established
`%LOCALAPPDATA%\CML\bin\odin.cmd` contract. Relative environment values are rejected,
and the same resolver feeds status, install, repair, and pairing.

The preload now normalizes rejected Odin IPC calls. Users see a concise install or
pairing error rather than Electron's remote-method transport prefix, while successful
results remain unchanged. A source-level regression prevents reintroducing
`app.getPath("localAppData")`; resolver tests cover direct, missing, and invalid
environment values; existing launcher tests continue to cover atomic repair, exact
PATH matching, environment broadcast, and shell-free bounded help probing.

Validation for this unbuilt source delta:

| Gate | Result |
| --- | --- |
| Focused Odin launcher and IPC tests | 9/9 passed |
| Desktop | TypeScript passed; 102/102 Electron tests passed |
| Production renderer build | Passed |
| Renderer HTML safety and interactive controls | Passed |
| Diff hygiene | Passed with line-ending notices only |
| Rebuilt Windows package and physical Odin install | Pending owner rebuild |

## July 28 Profile Authority And Chat Stream Repair

Profile state had three competing identities: onboarding setup state, Settings
renderer state, and a sidebar fallback derived from the vault directory name. Saving a
display name could therefore appear to succeed without becoming authoritative, while
an updated avatar remained absent from the sidebar. The renderer now reads and writes
the durable Electron setup profile, broadcasts profile changes, and resolves opaque
managed-media IDs consistently in Settings and the application shell. Partial updates
preserve the onboarding name and avatar. The opening-library page now displays only
the onboarding wordmark.

External drag-and-drop failed for the same class of process-boundary reason. React
passed DOM `File` instances through `contextBridge` to the preload. Those proxied
objects did not retain Electron's native file binding, so `webUtils.getPathForFile`
produced no usable paths and Sources displayed the browser-only fallback even in the
desktop app. The preload now observes the drop in the capture phase, while the native
objects are still valid, extracts paths there, and exposes a single-use array of plain
strings. All three drop surfaces consume that array before invoking the existing
bounded supported-file scan. Focused tests cover multi-file drops, one unreadable
entry among valid files, one-time consumption, and preload wiring.

The locked-library form also exposed an error-locality problem. The API already
returned a safe 401 code for an invalid passphrase, but the generic client formatter
rendered “Invalid Vault Secret.” in a Settings-wide banner above the active section.
Users working in the Library & Security section could not see whether the attempt had
failed. The client now maps that code to “Incorrect passphrase. Try again.” and the
form owns a dedicated inline error linked through `aria-describedby` and
`aria-invalid`. Editing clears stale feedback, Enter submits, other service failures
remain inline, and successful unlock clears the secret and error. The Unlock action
also remains available when the secured vault ID comes from lock status while ordinary
vault metadata is intentionally restricted.

The chat failure reported as “The local service closed the answer before confirming
it was saved” was traced from packaged stderr to Starlette's
`StreamingResponse.listen_for_disconnect`. The obsolete
`ReservedChatFieldMiddleware` had read the JSON body and replaced the ASGI receive
callable with one that returned the same terminal `http.request` forever. It had once
rejected the then-reserved complete-analysis field; after complete analysis shipped,
its validation was removed but the unsafe replay remained. The streaming response
expected `http.disconnect`, received the stale body, raised
`RuntimeError: Unexpected message received: http.request`, and canceled the answer
before the renderer observed `done`.

The middleware and its dead path helper are removed. Regression coverage now exercises
the actual FastAPI application and all remaining middleware, not only the route's body
iterator. It requires the full SSE sequence and verifies that durable generation state
is `completed`. Existing disconnect coverage still requires a terminal `stopped`
generation with exactly one saved partial answer. On the client, SSE parsing accepts
CRLF and multi-line data framing, and an incomplete persisted stream triggers a
timeline reload; completed, stopped, or retriable state is rendered from SQLite
instead of inventing a second assistant error message.

Validation for the combined unbuilt source delta:

| Gate | Result |
| --- | --- |
| Additional backend QA | 100/100 passed |
| Focused chat lifecycle | 3/3 passed |
| Desktop | TypeScript passed; 98/98 Electron tests passed |
| External-drop boundary | 3/3 focused tests passed |
| Unlock feedback | 2/2 focused contracts plus rendered wrong/correct interaction passed |
| Production renderer build and HTML safety | Passed |
| Python compile and diff hygiene | Passed |
| Rebuilt Windows package | Pending owner rebuild |

## July 28 Packaged Launch Failure And Model Import Reconciliation

The July 28 `0.1.9` package completed NSIS generation, but neither
`win-unpacked\CML.exe` nor an installed copy opened. An isolated launch reproduced the
failure before any startup-status file was written. `desktop-runtime.log` identified
the exact boundary: `loadStartupProgress` passed Chromium a roughly 2.2 MB encoded
HTML URL and `BrowserWindow.loadURL` failed with `ERR_INVALID_URL (-300)`.

The oversized URL came from embedding the 1,639,177-byte onboarding
`brand/Container.svg` as base64 inside a second percent-encoded HTML `data:` URL.
Installer success was unrelated because NSIS had correctly copied the same broken
application payload. Startup now loads the small packaged
`electron/startup.html` file directly. Its logo is the same
`dist/client/brand/Container.svg` asset used by onboarding, referenced rather than
duplicated. A package missing the startup document now opens the branded repair
document; only a package missing both documents receives a bounded text-only page.
Tests cap the startup document/fallback size and verify that the full wordmark is
never embedded in the HTML URL.

Two diagnostic scaling issues were fixed with the launch path. Desktop runtime log
values are capped so one invalid URL or stack cannot append megabytes per launch. The
package launch smoke test detects an early process exit instead of waiting for the
full timeout and reports a bounded runtime-log tail with the exit code. The original
artifact was rerun with isolated user data and reproduced the expected pre-fix
failure; it remains unchanged because the owner is performing the package rebuild.

The same work period corrected model state reconciliation. The UI previously showed
an import as ready even when no usable active model existed, kept Continue disabled,
and allowed repeated imports. That produced duplicate Qwen registry rows that still
could not run. Backend reconciliation now canonicalizes duplicate entries by identity
and artifact location, distinguishes imported from usable/active state, and avoids
advertising broken entries. Onboarding and Settings share the same model-state
derivation so a usable existing import can be selected, while interrupted or invalid
imports remain actionable without being called ready.

Validation evidence for the combined source state:

| Gate | Result |
| --- | --- |
| Full backend | 816 passed, 2 optional skips |
| Desktop | TypeScript passed; 94/94 Electron tests passed |
| Production renderer build | Passed |
| Renderer HTML safety | Passed |
| Diff hygiene | Passed; line-ending warnings only |
| Old packaged artifact reproduction | Expected failure confirmed: `ERR_INVALID_URL (-300)` |
| Fixed package launch | Pending owner-deferred rebuild |

## July 27 ChatGPT MCP, Tunnel, And Reliability Completion

The latest source completes the locally executable ChatGPT MCP and secure-tunnel
implementation. The remaining release boundary is now explicit:
the owner-deferred Windows package rebuild and its post-build checks, followed by tests
that require an authorized ChatGPT workspace and live OpenAI tunnel credentials.

MCP is divided into three layers. `bridge_mcp_tools.py` owns transport-independent
contracts, annotations, capability filtering, and strict argument validation.
`bridge_mcp_stdio.py` owns bounded newline JSON-RPC framing and concurrent dispatch.
`bridge_mcp.py` owns backend calls, safe error mapping, and result formatting. The
stdio path handles malformed and invalid UTF-8 input, oversized frames, partial EOF,
notifications, duplicate request IDs, cancellation, and overload. Retrieval, writes,
and lightweight calls have separate bounded capacities. Unsafe Unicode controls and
surrogates are rejected, backend resets are mapped to retriable safe errors, and the
entire serialized tool result—not merely one text field—is bounded without cutting
UTF-8 sequences.

The Electron tunnel manager stages only verified packaged helpers, passes a minimal
child environment, rejects non-loopback backend origins and symlinked manifest entries,
and sends the OpenAI runtime key through a temporary file rather than process arguments.
Windows safe storage protects the durable runtime and Bridge credentials. Credential
replacement is atomic, preserves the previous encrypted file on disk-full failure, and
fails closed when OS encryption is unavailable or a newer schema is present. Tunnel
readiness is loopback-only and monotonic-time bounded. Transient DNS, TLS, reset, 429,
and 5xx failures retry with exponential jitter; 401, 403, and version failures stop
automatic reconnect. Rapid disconnect, crash, stale-owner reconciliation, and orphan
cleanup have regression coverage.

Bridge settings and tunnel metadata have explicit compatibility schemas. Existing
Claude Desktop and Cursor clients survive database reopen. A newer Bridge schema is
refused rather than downgraded. Permission-sensitive Bridge client edits rotate the
token automatically; when that client owns the live tunnel, Electron reconnects with
the new token. Resetting setup or deleting the active vault disconnects and forgets
tunnel credentials first. Feature flags exist in both Electron and backend code for
ChatGPT setup, secure tunnel, write tools, future streaming, and future remote HTTP.
Write-disabled deployments downgrade to read-only rather than exposing unusable tools.

Write audit semantics were strengthened. Every recognized client write attempt is
recorded before authorization, including capability and scope denials, stale review
decisions, idempotent replays, and conflicting retries. Successful source captures and
review decisions also record completion. The lightweight `list_clusters` call records
client identity, source count, bytes, and success, allowing the desktop to detect an
actual ChatGPT verification call.

The ChatGPT setup interface is a numbered, resumable flow. It reconstructs its state
from persisted Bridge clients, allowed scope, tunnel metadata, and request history
instead of storing credentials or fragile renderer checkpoints. Copy explains that
workspace eligibility is controlled by ChatGPT and the workspace administrator. It
guides read-only/read-write selection, explicit scope, tunnel health, app/tool scanning,
a harmless `list_clusters` request, a confirmed test artifact for write mode, cleanup,
and immediate disconnect-and-revoke.

The latest source evidence is:

| Gate | Result |
| --- | --- |
| Full backend | 810 passed, 1 optional skip, 2 scale deselections, 0 failed; 286.55 s |
| Focused post-fix MCP/Bridge | 49 passed |
| Desktop | TypeScript passed; 91/91 Electron tests passed |
| MCP Inspector 0.21.2 | Development stdio read-only and read/write passed |
| MCP source soak | 1,000/1,000 calls; init 824.159 ms; tool list 1.552 ms; list p95 86.93 ms; max 160.779 ms; RSS growth 0 MiB |
| Odin scale | 50,000 files; 68.3 MiB peak; 160.824 s under concurrent Inspector load |
| Product scale | 10,000 sources queried in 0.108 s |
| Clean security drill | Pass; locked sources 423; revoked Bridge client 401 |
| Offline-at-rest drill | Pass; zero plaintext marker hits |
| Interrupted-flow drill | Pass before and after recovery |
| Large encrypted vault | 1,200/1,200 imported; 0 failed; query 195.14 ms; reconciliation complete |
| Dependencies | No known Python or production npm vulnerabilities |
| Diff hygiene | Pass; line-ending warnings only |

The first full-suite attempt exposed a direct-call edge case in the new audit preflight:
FastAPI's `Header(None)` sentinel reached token-length validation. The token boundary now
accepts strings only, the focused regression passed, and the clean full rerun produced
the result above. This is retained because it demonstrates why the post-change full
suite cannot be replaced by focused MCP tests.

Machine-readable source evidence is in `tmp/local-validation-20260727/`. Historical
packaged results remain under `tmp/`, but the existing installer predates the final
transport, audit, feature-flag, credential, scope-rotation, and setup-flow changes.
Those artifacts are not proof for the latest source. After the owner rebuilds, packaged
Inspector, soak, runtime/full-vault/OCR/migration, startup, rendered UI, Odin launcher,
package layout, install, and uninstall gates must all be repeated.

## July 26 Desktop Chrome And Model-Onboarding Stabilization

The latest source revision replaces the Windows native title bar with Vault-owned
window chrome. Electron creates a frameless `BrowserWindow`; the renderer reserves
a 32 px draggable strip and supplies minimize, maximize/restore, and close controls.
The IPC bridge resolves the sender's window instead of acting on a global window.
Onboarding, the normal application shell, and startup-repair screens all retain
window controls, while interactive controls are excluded from drag regions. Real
Electron QA at 125% Windows scaling confirmed drag, maximize, and restore behavior
without the former native title bar.

Managed-model setup also received three state-machine corrections. Recommendation
loading is limited to the initial request, so the 750 ms status refresh no longer
flashes `Loading model options`. The backend model row is authoritative for an
active download, preventing stale renderer progress from masking `installed`.
Terminal installed/cancelled notices fade after 1.8 seconds and unmount after 2.4
seconds in both onboarding and Settings. Finally, the Qwen activation probe sends
`/no_think`, disables thinking through chat-template arguments, and permits 32
output tokens. Runtime evidence showed that the old four-token probe could spend
its complete budget on hidden reasoning and then report an empty generation.

Validation includes 57 passing Electron tests, a passing production desktop build,
four focused managed-runtime tests, two focused onboarding QA tests, an
interactive-control audit across 42 TSX files, and a rendered Playwright
active-download-to-installed transition with no console errors. This is source and
development-build evidence. The existing 0.1.9 installer and unpacked application
were produced before this delta and must be rebuilt before package claims include
these changes.

## Current Source Of Truth

- Compact operating brief: `docs/PROJECT_CONTEXT.md`
- Public product overview: `ReadME.md`
- Public benchmark report: `BENCHMARK.md`

## Current Project Cycle

Vault is currently at version `0.1.9` and in pre-release stabilization and productionization. The core product direction is settled: local-first storage, retrieval-first context delivery, temporal memory, bounded evidence packets, and Odin-backed project context are the active architecture. The current cycle is not a broad feature-discovery phase.

The major scoped implementation passes are complete:

- the live product no longer depends on the former LoRA/expert architecture;
- chat and Bridge use the same grounded context contract;
- clusters have RAG-native indexing and profile lifecycles;
- temporal memory has persisted version history, provenance, user controls, and local refresh;
- Odin supports scoped project registration, durable synchronization, AST-derived structure, retrieval activation, CLI access, project-backed clusters, scoped questions, and request-only graph/tree artifacts;
- the desktop has first-class Projects, Tasks, Sources, cluster profiles, Settings Health, CLI Access, and evidence follow-up surfaces;
- benchmark tooling now separates ingestion, retrieval, packing, reading, judging, and reporting with resumable artifacts and regression gates;
- external-corpus validation now includes all 3,045 Open RAG retrieval questions and a frozen 500-question paid QA gate;
- production memory benchmarking now includes a frozen evolving-fact suite and an activation-only paired protocol that reuses unchanged answers and judgments;
- atomic-memory compiler v9 now runs in production chat-session sync, persists lossless facts and terminal source-unit coverage separately from the curated temporal ledger, exposes session-scoped loading, and records conservative named-entity category memberships for future retrieval activation;
- the public README and benchmark report describe the product and its measured results in user-facing language;
- the July 24 UI distillation removed redundant cluster inspectors, dead/stale controls and components, duplicate navigation, and several spacing/overflow failures while preserving a smaller explicit accessibility and packaged-desktop backlog;
- the July 26 desktop pass added frameless app-integrated Windows controls and corrected managed-model activation, polling, and terminal-notice behavior.

The remaining cycle is release work and quality productionization:

1. publish the active 0.1.9 frameless-shell, model-onboarding, and MCP source;
2. preserve the completed backend, desktop, Inspector, security, scale, dependency,
   and source-soak evidence while the owner prepares the package rebuild;
3. prove a production-shaped compressed late-interaction index before considering ColBERT activation;
4. evaluate future memory changes on fresh, preregistered evidence rather than the development-exposed LongMemEval set;
5. improve Odin's TypeScript/React graph-to-prompt selection and authoritative cross-file relationships;
6. rebuild the Windows installer from the latest source and complete
   account-separation and signing validation;
7. finish the remaining UI audit work in packaged Electron: accessibility, keyboard/zoom, offline and lock transitions, remaining stale route handlers, and Bridge/Settings decomposition.

The reviewed 0.1.9 packaging pass is published on `main`. GitHub CI run
`30182242079` passed the dependency audit, desktop, quick, integration, system,
and benchmark jobs; the dispatch-only Odin scale job was correctly skipped. The
development/test installer lifecycle passed. The project remains pre-release
because the latest source still needs a package rebuild and account-separation
and signing proof remain outstanding.

The July 21 atomic-memory v8 pass closes the production-ingestion disconnect identified in the v7 review. `sync_chat_session_temporal_facts` now also regenerates a dedicated atomic tier with immutable source hashes, message provenance, source-unit terminal status, compiler-version state, retraction on source edits, and idempotent resync. Existing temporal retrieval remains unchanged. Generic explicit category counts are normalized as closed cardinalities, and conservative progressive counters support an explicit base such as “I have 4 projects” followed by an unambiguous singular increment. A forced, model-free replay of both frozen 200-question development sets preserved 4/200 and 5/200 activation, 100% activated correctness, zero false-safes, and 100% source-unit coverage. This is a production capability improvement, not a benchmark accuracy gain; broader category membership/coreference remains the activation blocker.

The follow-on v9 pass adds explicit title/apposition membership facts and a small general alias ontology: for example, `Dr. Lee` and “Morgan Hale is my physician” produce canonical doctor memberships, while doctor/physician/clinician query aliases are exposed by the question plan. These memberships are deliberately marked open-world, so they improve candidate retrieval but cannot certify a complete distinct count. A privacy-preserving coverage inspector can back up and backfill a chosen local database, then report only aggregate yield and coverage metrics. No populated chat vault was present on the development machine: both discovered application databases had zero sessions/messages. The v9 forced replay preserved the v8 gates at 4/200 and 5/200 activation, 9/9 correctness, zero false-safes, and 100% source coverage; readiness remains NO-GO solely on activation.

## Architecture State

The project has completed its migration away from the LoRA cluster-expert path.

The live architecture is now RAG-only:

- retrieval is the evidence authority
- clusters are retrieval scopes with cached profile metadata
- chat and Bridge share a retrieval-first packet contract
- Odin can append bounded, snapshot-proven graph/tree context for explicit internal or external requests without exposing a permanent graph UI
- Odin synchronization runs through immutable candidate manifests and persisted discovery, structure, retrieval, activation, and cleanup jobs; active retrieval membership changes only in the activation transaction
- Odin projects persist either a broad `context` discovery scope or a source-focused `code` scope; the choice is available in the CLI, API, and project settings and is recorded on each snapshot
- Odin CLI access uses desktop-approved scoped clients, a non-secret runtime descriptor, short-lived sessions, and a Windows user-protected credential helper
- Odin structure extraction uses a versioned offline registry for Python, JSON, JavaScript/TypeScript/TSX (including `.mjs`, `.cjs`, `.mts`, and `.cts`), Go, Rust, Java, C#, C, and C++
- token reduction comes from packet shaping and cache reuse, not adapter compression
- desktop setup and packaged runtime no longer expect a second expert runtime

The earlier bundle/expert-compression architecture is historical only and should not be treated as the current product contract.

## What Changed In The Migration

The migration replaced the old `retrieval + LoRA expert` direction with a single RAG stack:

- removed LoRA runtime, training, evaluation, proof, and artifact lifecycle code
- removed expert-oriented cluster statuses and replaced them with RAG-native lifecycle fields
- moved cluster refresh to indexing-driven summary/glossary refresh
- unified chat and Bridge on the same packet shape
- removed onboarding, settings, and packaging assumptions about an expert runtime
- converted the live model recommender path to chat-only compatibility logic

Current cluster metadata now centers on:

- `index_status`
- `profile_status`
- `cluster_summary`
- `cluster_glossary`
- `profile_updated_at`
- `profile_source_hash`
- `indexed_source_count`

## Validation That Passed

The migration has already been validated beyond static code changes.

Live isolated validation passed:

- `search/semantic` returned grounded hits from the seeded RAG vault
- `chat/context` returned grounded citations and retrieval fallback output
- `bridge/context` returned grounded citations and cluster profile data
- desktop screens validated against the isolated backend loaded without console errors on the checked paths

Broader regression validation passed:

- current combined backend collection: `810 passed`, `1 optional skip`, and `2`
  explicit scale deselections, with only the existing Starlette TestClient
  deprecation warning;
- focused backend regression slice: `127 passed`
- Electron behavior tests: `91 passed` on the July 27 source slice
- backend tests are classified automatically into non-overlapping quick, integration, system, benchmark, and scale tiers
- quick: `147 passed`; integration: `214 passed`; system: `120 passed`
- benchmark: `16 passed`, `1 skipped` when optional TurboVec was unavailable
- manually dispatched 50,000-file scale test: `1 passed` in 555.50 seconds
- npm dependency audit: `0 vulnerabilities`
- desktop typecheck and production build passed after the July 13 cleanup

Scale and token-reduction validation passed:

- synthetic user corpus benchmark with `60` files passed
- retrieval benchmark with `500` sources passed
- Odin's reviewed language corpus is deterministic across three runs and preserves unsupported/malformed files for text retrieval
- the opt-in 50,000-file Odin discovery gate passed in `126.2 s` with `68.3 MiB` peak traced memory
- desktop project, Tasks, and answer-evidence interactions passed against an isolated live backend at the 1024 px minimum without page-level horizontal overflow or console errors
- three clean external runs were deterministic for both tools: Odin indexed Flask in a 1.920-second median and Zustand in 1.731 seconds; Graphify 0.9.17 took 31.091 and 10.586 seconds respectively under its different `--code-only` scope
- a six-question local Qwen2.5-1.5B-Instruct evaluation scored Odin graph slices at 0.500 mean fact-group recall, Graphify at 0.458, and no graph at 0.250; the small gap is directional rather than a general quality ranking
- a one-run, code-scope follow-up on Django and React kept file counts within 2.2% and 0.6% between tools; Odin was 8.32x and 7.69x faster with substantially lower sampled process-tree memory, while Graphify retained a broader cross-file relationship vocabulary
- the Django/React Qwen2.5-1.5B-Instruct follow-up scored Odin at 0.333 mean exact fact-group recall, Graphify at 0.167, and no graph at 0.250; only one answer was complete, exposing graph-slice ranking and hallucination grading as the next interpretability bottlenecks
- the release LongMemEval-S pass now covers all 500 cleaned questions: retrieval recall@10 was 0.9802; Kimi K2.6 accepted 83.0% and the pinned GPT-5.4 independent judge accepted 84.8%, with 96.6% judge agreement and Cohen's kappa of 0.8742
- the tokenizer-aware chunker has been projected over all 23,867 LongMemEval sessions: 269,270 chunks, zero above the 240-token target, and 30.8% fewer raw chunk tokens than the release index; the release accuracy numbers remain unchanged until the index is rebuilt and rerun
- LOCOMO's weak single-hop and multi-hop results are not caused by embedding truncation because every dialog-turn document fits the model; widening the existing hybrid candidate pool raises recall from 0.6031 at 10 to 0.7948 at 50, establishing reranking and evidence packing as the next measured optimization
- simple weighted RRF and score-weight tuning did not materially improve held-out LOCOMO recall; a local MiniLM cross-encoder raised recall@10 from 0.5932 to 0.7138 on the canonical 100 and from 0.6031 to 0.7076 on the full 300, but production remains unchanged pending packaging, latency, and source-diversity gates
- AVX2 INT8 ONNX preserved cross-encoder quality and reduced the graph to 23.2 MB, but measured 274-290 ms/query at depth 50 and therefore failed the sub-100 ms production gate; product dependencies remain unchanged
- most LongMemEval multi-session and preference reader failures already had complete gold evidence, which prioritizes structured evidence presentation over speculative consolidation
- the fingerprinted structured reader recovered 9/22 complete-evidence multi-session failures under both judges, compared with baseline acceptance of 2/22 by Kimi and 0/22 by GPT; because the set was selected on GPT failure and recovery missed the 50% gate, a matched previously-correct control is required before production use
- the matched structured-reader control retained 20/22 questions that both judges previously accepted, exactly meeting the 90.9% gate; the balanced failure/control diagnostic gained nine answers and regressed two, but the two count/date aggregation failures require a fresh held-out v2 prompt test before production use
- the fresh 25-question structured-reader v2 holdout failed both preregistered gates: dual-judge retention was 13/18 and recovery was 0/7 with 100% judge agreement; v2 remains experimental and the full-500 rerun was correctly skipped
- preference synthesis and count aggregation now require question-type-specific reader experiments; adding more universal prompt rules is not supported by the evidence
- the Mem0 public harness review favors saved multi-cutoff retrieval, separate predict/evaluate phases, resumability, per-question traces, controlled ablations, and large-scale retrieval tests while reinforcing Vault's use of stricter official judging and independent judge agreement
- routed-reader v3.2 did not pass promotion on a fresh 30-question set that excluded all 69 earlier development/control questions: retention was 17/20 against an 18/20 gate, while recovery was 3/10, every control stratum was at least 80%, judge agreement was 93.3%, prompt tokens were 0.9308x baseline, mean latency was 0.8134x baseline, and routes matched exactly
- the failed retention gate blocked both the tokenizer-safe rebuild and the full-500 paid rerun; the next reader experiment must separately fix cumulative snapshot handling, chronological event ordering, and hard anti-preference filtering before using another untouched holdout
- routed-reader v4 fixed the cumulative-snapshot and chronological-order development regressions, then failed a second fresh promotion set by the same one-control margin: 17/20 retention against 18/20, with 4/10 recovery, 93.3% judge agreement, all control strata at least 80%, prompt tokens at 0.9585x baseline, latency at 0.7964x baseline, zero route mismatches, and zero content filters
- the v4 gate again blocked the tokenizer-safe rebuild and full-500 run; the next memory-reader architecture should type evidence provenance, numeric roles, cumulative state, dates, and preference polarity before deterministic reduction instead of extending the prompt again
- a manual zero-API scoping fixture confirms the typed-evidence boundary: citrus counting and French-press state comparison are fully deterministic once provenance/date/numeric roles are encoded, while slow-cooker advice needs LLM synthesis constrained by required personalized anchors
- a production Kimi/GPT pass on 30 Django and React questions accepted 5/30 Odin answers and 3/30 Graphify answers under GPT-5.4 at a 16,000-character budget; all accepted answers were Django, so React/TypeScript slice ranking remains the active Odin interpretation-quality gap
- required-fact substring matching is retained only as a lexical mention diagnostic because answers can list expected symbols while saying the evidence is missing
- `tree-sitter` is pinned to 0.25.2 because 0.26.0 caused reproducible native access violations on valid external TypeScript/TSX inputs

## Odin Project Context

Odin's scoped release implementation is complete in live code.

The active project contract now separates:

- persisted discovery scope (`context` by default or source-focused `code`)
- accepted manifest freshness
- structure readiness and `active_structure_snapshot_id`
- retrieval readiness and `active_retrieval_snapshot_id`
- optional interpretation, which remains unavailable unless a future local interpretation layer is enabled

Candidate sources have no active cluster membership and use candidate-only chunk state. Discovery and structure may become visible independently, but ordinary retrieval continues to resolve through the prior active snapshot until candidate chunks and membership are activated atomically. This also applies when the discovery scope changes. Cancellation and interrupted-worker reconciliation preserve the prior usable index. Custom include/exclude scopes remain deliberately deferred.

The canonical desktop project route loads aggregate project facts rather than all files or graph nodes. It exposes live progress, cancellation, layer status, freshness, scoped chat entry, run history, folder reconnection, cluster links, layer-specific reindex, and safe removal. Graph/tree views remain on demand. Project-grounded answer citations disclose only the evidence used by that answer, including path, line span, symbol, snapshot/commit, excerpt, and local file actions.

The remaining Odin-adjacent product items are deliberate deferrals rather than incomplete promises: project interpretation, automatic watch/hooks, remote repository indexing, cross-project retrieval until its citation/freshness contract is proven, Tier C languages, and non-Windows credential helpers. Separately, graph-to-prompt definition ranking and typed relationship expansion for TypeScript/React are active quality work identified by the production-model benchmark, not deferred product scope.

## Current Token Reduction Interpretation

The old token-reduction story depended on expert compression. That is no longer true.

The current RAG system reduces tokens through retrieval, evidence selection, and bounded packing:

- selects only relevant evidence
- trims and deduplicates citations
- reuses working memory
- reuses cached cluster profile material
- represents temporal facts and typed claims compactly where their provenance can be preserved
- enforces explicit packet budgets and records packed, final-request, and cumulative usage

There are two distinct measurements and they should not be combined:

1. Earlier product packet telemetry measured `1,858.62` average raw tokens against `1,030.38` final packet tokens, a `44.43%` average reduction. Warm-cache repeat-query behavior measured a `94.8%` reduction in that earlier benchmark. This remains directional operational evidence.
2. The full 500-question LongMemEval comparison is the stronger current controlled result. Claim-first v2 reduced mean reader prompt usage from `33,331.9` typed-v1 tokens to `8,307.1`, a `75.08%` reduction. Cache-adjusted reader-plus-dual-judge cost fell from `$13.4211` to `$4.5111` (`66.39%`), and mean reader latency fell from `11.41 s` to `4.49 s` (`60.68%`). Kimi accuracy moved from `83.8%` to `81.8%`; GPT-5.4 accuracy moved from `83.2%` to `82.0%`.

For a workflow shaped like 100 LongMemEval questions, that means approximately:

| Measurement | Typed-v1 | Claim-first 10K | Difference |
| --- | ---: | ---: | ---: |
| Reader prompt volume | 3,333,190 tokens | 830,710 tokens | 2,502,480 fewer |
| Equivalent sequential reader latency | 19.0 min | 7.5 min | 11.5 min less |
| Recorded reader + dual-judge evaluation cost | $2.68 | $0.90 | $1.78 less |
| Kimi-accepted answers, projected from the full set | About 84 | About 82 | About 2 fewer |

The same reader-prompt allowance therefore supports about four times as many similarly shaped questions under claim-first packing. All 500 measured claim-first questions stayed within both the final and cumulative 10,000-token budget.

The `75.08%` number is a prompt-volume reduction, not a universal bill discount. The `66.39%` cost reduction belongs to the recorded reader-and-two-judge protocol. Normal product use may omit judges, and actual billing varies with model, provider price, cache use, answer length, and source/question complexity.

Benchmark ingestion is local. Parsing and embedding the measured corpora produced zero billable extraction or embedding API tokens. That moves ingestion cost to local CPU, RAM, disk, time, and electricity; it does not make ingestion resource-free.

This is the current product story: Vault reduces repeated corpus replay through grounded selection and bounded context, while exposing the quality and resource tradeoff.

## Remaining Non-Migration Work

The migration is complete. Remaining work is divided into release gates and measured product-quality work.

Release gates:

- rebuild and repeat clean-machine packaged validation from the latest source;
- prove account separation, vault protection, package integrity, and signed-installer behavior;
- rerun the full backend tier matrix, desktop typecheck/build, Electron tests,
  dependency audit, and packaged smoke tests against the final 0.1.9 tree;
- monitor the upstream Starlette TestClient compatibility warning and the existing frontend bundle-size warning;
- keep optional local synthesis setup understandable while preserving retrieval-draft fallback.

Product-quality work:

- build a compressed persistent ColBERT proof of concept with lifecycle, deletion, migration, concurrency, licensing, package-size, RAM, disk, and latency measurements;
- validate late interaction across another corpus before changing production retrieval;
- improve claim selection, temporal reconciliation, numeric aggregation, preference constraints, and multi-session synthesis on a fresh evaluation set;
- expand deterministic typed reducers only where the evidence contract can remain authoritative and cited;
- improve TypeScript/React Odin graph slices and authoritative import, reference, and re-export relationships;
- repeat Odin interpretability evaluation with more than one model and multiple runs;
- resume accessibility and broader UI QA after the backend/retrieval shape stabilizes.

## July 13 Product Integrity Pass

The desktop UI and repository were audited for false, stale, and developer-facing surfaces.

Changes that now define current behavior:

- Home no longer has a health/quick-action/activity right rail; Quick Actions lead into the prompt and Activity follows Suggested Clusters.
- Cluster progress uses real indexed-source ratios and all shared progress components clamp values to `0–100`.
- Settings Health shows live service, library, database, memory-search, local-chat, task, OCR, and hardware results.
- The Map route no longer accepts or substitutes seeded demo content.
- Chat no longer shows a fabricated cluster count when no library is open.
- Onboarding no longer advertises an unimplemented Google account flow.
- Production routes no longer consume seeded state or mock reply generation. The mock vault store is retained as an explicit development fixture, protected by a test that prevents production route/component imports.
- The reusable UI primitive inventory is retained for future feature work; only obsolete product-specific code remains deleted.
- A shared encrypted-source hydration bug was fixed so authorized search, memory, and report paths receive all decrypted fields without restoring plaintext database storage.
- README and live interface copy now address users directly and reserve backend/runtime terminology for advanced settings and diagnostics.
- Historical audits and completed implementation plans are retained only as local,
  ignored working records. Current behavior remains documented here and in
  `docs/PROJECT_CONTEXT.md`.

The Odin release plan, parser dependency decision, and external benchmark are local working records intentionally excluded from Git. Implemented behavior and release status remain summarized in `PROJECT_CONTEXT.md`. The desktop includes a first-class Projects navigation destination and lightweight project index; project details remain centered on status, scoped questions, and run activity, with graph/tree artifacts shown only when requested.

Important distinction:

- missing local synthesis runtime is not a migration bug
- it only means chat falls back to retrieval-draft output instead of local grounded synthesis

## Historical Note

Security audit and build records may retain LoRA references where they document
historical threat analysis. They are not live product contracts.
`docs/PROJECT_CONTEXT.md` is authoritative.

## July 18 Memory Benchmark Update

The latest typed-v1 LongMemEval-S result is 83.8% with the Kimi judge and 83.2% with the pinned GPT-5.4 independent judge over all 500 questions. Agreement is 97.8%, retrieval recall@10 is 0.9802, and stored typed-evidence citations are 100% valid. Only two questions were answered deterministically, so the 3.94% realized cost improvement is attributable to provider caching rather than broad evidence compression.

LongMemEval and LOCOMO now have separate diagnoses. LongMemEval is chiefly an evidence-presentation, temporal, and synthesis problem because retrieval is already strong. LOCOMO is chiefly a candidate-generation and ranking problem because recall@10 is 0.6031; broader candidates and the validated cross-encoder improve it, but the reranker has not met the desktop latency gate.

The active memory roadmap is: temporal invalidation and explicit fact histories; immutable assistant/user provenance; bounded evidence packing with evidence/scaffolding token accounting; production-grade reranking; broader typed reducers; then full LOCOMO-1540 and BEAM evaluation. Vault's current target user is a developer or knowledge worker who values local ownership and unified code, project, document, and conversational context more than hosted sub-200-ms retrieval or benchmark-leading multi-session accuracy.

The temporal-memory product layer is now operational end to end. A persistent append-only fact ledger stores cluster-scoped versions with immutable speaker/source provenance, citations, validity windows, and supersession links. Extractor v3 covers conservative preference, state, action, plan, identity, locale, role, language, goal, decision, habitual choice, favorite category, and explicit-memory statements; assistant recommendations remain suggestions and cannot become completed user actions. Current facts enter grounded memory packets automatically, while dated questions select the historically valid version.

The product lifecycle around that ledger is also live. General state and preference reversals preserve their histories, written and relative `as of` dates resolve deterministically, and every processed chat session receives a versioned content fingerprint even when it yields no facts. New completed chats enter the ledger through the transcript-memory job. On startup, Vault now detects legacy chat sessions with no state, an older extractor version, or a changed message count and queues one deduplicated local backfill per affected vault. Users can still inspect recent current facts, correct them through immutable replacements, remove them from future answers, inspect aggregate coverage, and start a resumable refresh from Settings > Library storage. The work uses the existing cancellable Tasks queue, skips unchanged current-version conversations, stays behind the unlock boundary, and makes no paid model calls.

Context reduction is now observable on real saved chat turns rather than inferred only from benchmark runs. Retrieval snapshots persist the packing strategy, candidate and selected citation counts, and split estimated token totals for prompt, evidence, history, memory, raw context, and final context. The UI reports aggregate reduction and average final context size without exposing query text or evidence contents. This telemetry is local operational feedback; it does not alter ranking or answers to improve a score.

The current product and benchmark-tooling slice is covered by 593 passing backend tests with 2 intentional skips. The latest desktop TypeScript check and production client/SSR build remains the previously recorded pass; existing bundle-size and external TanStack warnings remain unchanged.

## July 19 Bounded Evidence And Odin Ranking Update

The 10K claim-first LongMemEval v2 run is the frozen full-set baseline: Kimi accepted 409/500 answers (81.8%), the pinned GPT-5.4 judge accepted 410/500 (82.0%), agreement was 97.4%, and no final or cumulative reader request exceeded 10,000 tokens. Mean actual reader-prompt usage was 8,307 tokens, a 75.08% reduction from the earlier 33,332-token mean. This protocol is different from earlier typed-v1 and release-reader runs, so their scores must not be combined.

A deterministic failure dataset now separates retrieval, packing, reading, provider, and judging stages. Of 97 answers rejected by at least one judge, 43 are classified as claim selection or paraphrase, 18 as reader reasoning, 17 as judge/rubric mismatch, 15 as retrieval omission, 2 as judge disagreement, 1 as provider refusal, and 1 as reader truncation. A separate question-family grouping contains 56 temporal, 15 numeric, 9 preference, 9 supersession/latest-state, 6 fact-selection, and 2 cross-session questions. Those family labels derive from question type and wording; they are useful for slicing results but are not causal findings. In particular, they do not establish 56 temporal-resolution defects.

The evidence-packing prototype now has a thin deterministic ledger aligned with the production temporal and typed-evidence semantics. It records assertion mode, numeric role, event role, source authority, and query overlap; it does not replace authoritative raw evidence or the production temporal-fact store. On an apples-to-apples 500-question offline replay, ledger v3 retained the same 0.978767 answer-session recall, stayed under budget on every question, reduced the mean estimate by 0.5%, and moved literal gold containment from 0.496 to 0.492. That 0.004 change passes the declared 0.01 containment gate but does not establish an accuracy improvement; another paid full-set run is therefore unwarranted.

Odin graph projection now gathers candidates for every meaningful query term before applying a single ranking. Exact source symbols and broad term coverage outrank incidental prefix matches, while test, fixture, generated, and vendor nodes are demoted. Relationship traversal remains limited to extracted or user-confirmed typed edges, preserving evidence provenance. A model-free CI checker now enforces memory packet budget, recall, containment, and size gates.

All 500 LongMemEval items and prior routed-reader holdouts are development-exposed. Future promotion claims need a preregistered untouched partition or a different benchmark. A full standard LoCoMo retrieval pass is the next zero-API breadth check; it measures retrieval generalization, not LongMemEval reader accuracy.

The full LoCoMo breadth check is complete across all 1,540 standard questions. Recall@10 is 0.629493 and the any-evidence hit rate is 0.703776, improving on the earlier 300-question sample rather than collapsing. Mean retrieval latency is 280 ms and P95 is 626 ms. Recall rises to 0.698083 at 20 candidates, 0.739295 at 30, and 0.797389 at 50. Of the evidence-bearing questions, 372 can recover additional evidence solely by moving positions 11–50 into the first ten; 217 still have no annotated evidence in the first 50.

The failure pattern is category-specific. Category 1 has 158 ranking-recoverable questions and 141 with only partial evidence at 50. Category 3 has 32 ranking-recoverable questions and 32 with zero evidence at 50. This means a faster reranker can materially help both, but Category 3 also requires better candidate generation.

Session-diversity caps are negative evidence: every tested cap from one through five results per session reduced recall, so no diversity rule was added. The local INT8 MiniLM cross-encoder improves full-set recall to 0.703600 at depth 30 and 0.680075 at depth 20, with no category regression. Mean combined latency passes the 500 ms gate, but P95 reaches 1.09 s and 1.17 s against the declared 850 ms ceiling. The reranker therefore remains an experimental benchmark component and is not a packaged production dependency. The next ranking experiment needs a smaller/faster model, cached document representations, or a late-interaction design that preserves the measured recall gain without serial cross-encoding latency.

The zero-at-50 failure audit points to semantic mismatch rather than long or unusually temporal questions: failed questions average 0.0488 lexical overlap with their annotated evidence, compared with 0.3438 outside the failure group. A conversational MiniLM drop-in did not solve it; `multi-qa-MiniLM-L6-cos-v1` reduced recall@10 to 0.606677 and increased zero-at-50 failures to 230.

The next architectural experiment succeeded at retrieval level. Exact semantic-only ColBERT using `lightonai/answerai-colbert-small-v1` raised recall@10 to 0.760586 and recall@50 to 0.889430 over all 1,540 standard questions. All four categories improved, zero-at-50 failures fell from 217 to 100, P95 CPU query latency was 75.8 ms, and the uncompressed token-vector index was 10.1141 times the 384-float dense baseline. This passes the preregistered retrieval, category, latency, and storage gates, but remains a prototype until cross-dataset behavior, model licensing/packaging, persistent-index migration, and end-to-end reader quality are verified.

The July 20 compressed-index scale experiment moved this work from an exact in-memory prototype to a persistent 2-bit FastPLAID proof. The primary shard contained the 5,882 real LoCoMo turns plus deterministic vault-like distractors; three additional 50K distractor shards brought the stopped test to exactly 300,000 items. The combined index stored 16,305,967 token vectors in 1.1335 GiB, or 4,057 bytes per item. That is 19.44% of the 5.831 GiB raw float-vector representation and 2.64 times an equivalent one-vector-per-item 384-float dense index. Local GPU encoding accounted for 6.5 minutes and CPU index work for 73.8 minutes, with no paid API ingestion, reader, or judge calls.

On 100 fixed evidence-bearing LoCoMo questions, the 100K monolithic checkpoint produced 0.730278 recall@10 and 0.384981-second P95 global search. At the final scale, routing to the 150K primary shard preserved 0.730278 recall@10 with a 0.538606-second P95. Sequential global fan-out across all four shards also preserved recall in this controlled corpus, and no synthetic result entered the merged top 10, but P95 rose to 0.864851 seconds with a 1.102211-second maximum and 4.45 GiB peak query-process RSS. The global path therefore narrowly fails the existing 850 ms desktop gate. The synthetic corpus validates capacity and operational scaling rather than general real-world retrieval quality or cross-shard score calibration.

Incremental index lifecycle remains the stronger blocker. Five-thousand-item update time rose from 20.4 seconds near creation to 86.2 seconds at 100K. Twenty-five-thousand-item updates took 537.2 and 629.6 seconds and drove process RSS to 5.18 GiB; increasing the centroid-expansion buffer preserved recall but stored the pending append largely uncompressed, while reducing K-means iterations did not improve update time. Sharding bounds rewrite cost, but whole-vault querying transfers cost into latency and memory. The resulting decision is not to activate ColBERT universally. Continue only toward an opt-in, cluster-scoped compressed index with dense/BM25 fallback, and require deletion/compaction, crash recovery, encryption and lock eviction, RAM ceilings, packaging/licensing, and a second real corpus before promotion.

## July 20 Shared Claim Semantics And Consolidation

Claim extraction is now shared between production temporal ingestion and bounded benchmark evidence packing. The pure extractor returns only explicit source-verbatim claims and carries their subject, predicate, object, assertion kind, modality, supersession topic, confidence, and citation excerpt. Extractor v3 fixes compound first-person statements such as a positive and negative preference joined in one sentence, and adds conservative forms for `enjoy`, `can't stand`, `would rather`, and named favorite categories. The extractor version bump causes the startup migration detector to queue local idempotent backfills for older session states.

The production memory path now creates a derived consolidation item for preference or explicit history questions only when at least two sessions contribute. Its summary is assembled from structured facts, while its detail retains dated current/superseded labels, exact excerpts, fact IDs, source IDs, session IDs, and validity timestamps. The item never replaces the authoritative facts: individual source-backed temporal items remain available in the same packet. Explicit `as of` queries continue to use the fact version valid at that time rather than mixing a history profile into the answer.

The benchmark packer has a separate opt-in `claim-consolidated-v1` protocol. It atomizes compound claims, anchors all source claims belonging to a cross-session topic, and emits a clearly labeled navigation index only if at least two cited sessions survive packing. The gate compares overall budget, answer-session recall, literal containment, and mean tokens, plus independent recall and containment checks for multi-session and preference questions.

On the frozen 500-question LongMemEval retrieval artifact, consolidated v1 preserved 0.978767 answer-session recall, 0.492 literal containment, and zero over-budget packets. Mean estimated prompt tokens fell from 9,032.54 to 9,004.75, a 0.308% reduction. Multi-session and preference offline recall/containment were unchanged. Only one question formed a cross-session consolidation group, so no paid reader run or accuracy claim is justified from this corpus.

A new deterministic provenance protocol supplies the missing direct coverage. Nine controlled cases test compound preferences, exact and formatting-normalized reversals, a favorite update, a location update, habitual and first-choice paraphrases, user-versus-assistant attribution, and a no-durable-claim input. It measured 9/9 passing cases, 100% exact-claim precision and recall, 100% citation validity, and 100% expected-source retention with zero paid API calls. This fixture is a product regression gate, not a generalization or competitive benchmark.

The next accuracy slice is implemented in the production typed-evidence adapter. Preference questions no longer route through the personalized-advice reducer: a dedicated reducer chooses the latest current cited claim per normalized topic, while explicit history wording admits the previous version. Current preference and advice paths remove superseded rows before reduction. Advice may combine compatible experience and interest anchors across sessions after query-topic filtering, preserving both citations and falling back when either anchor is absent.

Temporal extraction now separates an event expression from the structured object. Completed actions with deterministic day-level expressions (`today`, `yesterday`, an integer number of days or weeks ago, or `on YYYY-MM-DD`) receive a resolved event date with resolution provenance. `last week` is stored as a start/end interval with week precision. State validity is never moved backward from message observation merely because a retrospective sentence contains an older event expression, preventing an old recollection from superseding a newer current state.

The follow-up review tightened four interpretation boundaries. Equal scoped and global recall is not evidence that active-cluster-only search is universally safe because the added shards contained no annotated cross-cluster evidence. The 4.45 GiB process peak cannot be linearly extrapolated to one million items because allocator behavior, memory mapping, model state, and concurrency were not isolated. The 86.2-second 5K update belongs to the 100K checkpoint, while the two 25K measurements extended the primary shard from 100K to 150K rather than operating at 300K. Finally, the controlled question set does not establish cross-corpus quality or independent-shard score calibration.

The next production-shaped hypothesis is a bounded staging index searched alongside a read-only compressed shard. New and changed records become searchable through staging; canonical live-record filtering and tombstones suppress deleted or revoked content immediately. A background job rebuilds a new compressed shard from canonical source records, verifies its manifest and retrieval smoke tests, and atomically activates it while retaining the old shard for rollback. This remains an experiment because FastPLAID compaction may still rewrite substantial state and require temporary disk amplification. A runtime resource governor must gate initial activation and unload late interaction under sustained memory pressure, falling back to dense/BM25 without losing canonical access. Vault lock must make all derived search state inaccessible and evict loaded index state.

Licensing is only partly resolved. The upstream `answerdotai/answerai-colbert-small-v1` model declares Apache-2.0, and the installed PyLate and FastPLAID distributions contain MIT licenses. The converted `lightonai/answerai-colbert-small-v1` snapshot used in the benchmark does not declare a license in its own metadata. Exact snapshot provenance, notices, hashes, redistribution permission, and packaged size therefore remain shipping gates.

The backend suite remains green after the benchmark and projection tooling: 593 tests pass and 2 skip. The prior raw-content deprecation was fixed; one upstream Starlette TestClient compatibility warning remains non-blocking.

The corrected top-10 ColBERT trace has also completed the full paid reader and dual-judge pass. Across 1,540 questions, official LoCoMo token-F1 is 0.5259, Kimi K2.6 accepts 1,028 answers (66.75%), and pinned GPT-5.4 accepts 985 (63.96%). Judge agreement is 92.01% with Cohen's kappa 0.8238, no reader response terminated for length, and total measured cost is $1.738753. On the exact 300 IDs used by the prior dense-hybrid run, retrieval improves from 0.603056 to 0.764112, token-F1 from 0.4373 to 0.5065, Kimi acceptance from 59.33% to 66.00%, and GPT acceptance from 56.33% to 63.33%. Because the reader was regenerated, the paired result measures the end-to-end system change rather than a deterministic retrieval-only delta.

## July 19 Benchmark And Public Documentation Consolidation

The benchmark story has been consolidated into two public layers:

- `ReadME.md` contains the short product-facing summary: latest headline results, practical workflow implications, comparison boundaries, and a link to the complete report.
- `BENCHMARK.md` contains the analytical record: benchmark suites, protocol stages, model roles, headline tables, charts, category results, full-run lineage, token and cost accounting, budget compliance, failed and rejected experiments, ingestion economics, competitive qualifications, tradeoffs, and local artifact locations.

`BENCHMARK.md` uses the same visual language as the README: the Vault logo, centered title/subtitle, restrained badges, compact navigation, GitHub callouts, tables, Mermaid charts, and a matching footer. The information hierarchy borrows the useful pattern of introducing the suite, then the ingest-to-evaluate workflow, then results and methodology. It does not present experimental internals as user-facing product features.

The public headline table now records:

| Benchmark and configuration | Questions | Retrieval | Kimi | GPT-5.4 | Reader prompt tokens/query | Evaluation cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Open RAG frozen QA prefix | 500 | 0.9380 section Hit@10 | 83.8% | 73.6% | 2,672.1 | $1.9102 |
| LongMemEval-S typed-v1 | 500 | 0.9802 recall@10 | 83.8% | 83.2% | 33,331.9 | $13.4211 |
| LongMemEval-S claim-first 10K | 500 | 0.9802 recall@10 | 81.8% | 82.0% | 8,307.1 | $4.5111 |
| LoCoMo ColBERT | 1,540 | 0.7606 recall@10 | 66.75% | 63.96% | 650.4 | $1.7388 |

The practical-stat section translates the controlled LongMemEval delta into a 100-question workload. It reports 3.33M versus 0.83M reader prompt tokens, about four times as many questions within the same prompt-token allowance, 19.0 versus 7.5 minutes of equivalent sequential reader latency, and `$2.68` versus `$0.90` in the recorded reader-plus-dual-judge protocol. It also reports the quality cost: roughly 84 versus 82 Kimi-accepted answers and 83 versus 82 GPT-accepted answers per 100. This prevents an efficiency claim from hiding its accuracy tradeoff.

The later Open RAG addition is a distinct document-QA workload. Its 2,672.1 prompt tokens/query is reported separately and is not substituted for the LongMemEval context figure.

The public wording explicitly separates:

- prompt-token volume from provider billing;
- benchmark reader-and-judge cost from ordinary product inference cost;
- zero billable API ingestion tokens from zero local resource use;
- retrieval recall from answer correctness;
- the best measured accuracy configuration from the best measured cost-quality configuration;
- prototype retrieval results from production-enabled behavior.

The report deliberately does not claim that every user will save exactly 75.08% or 66.39%. Those are controlled benchmark deltas. Real workloads vary with corpus size, evidence density, question type, model, answer length, caching, and whether evaluation judges are present.

## Current Benchmark Interpretation And Competitive Position

LongMemEval and LoCoMo diagnose different layers:

- LongMemEval retrieval is already strong at 0.9802 recall@10. Most remaining failures are claim selection/paraphrase, temporal resolution, numeric aggregation, preference synthesis, supersession, or reader reasoning after relevant sessions were found.
- LoCoMo remains retrieval-sensitive. Moving from the dense-hybrid baseline to exact semantic-only ColBERT increased recall@10 from 0.629493 to 0.760586, reduced zero-at-50 failures from 217 to 100, and raised end-to-end answer scores on the exact 300-question comparison.

The product therefore needs two different next moves: improve typed, provenance-aware evidence shaping for long-history synthesis, and productionize a compact late-interaction candidate index for conversational retrieval. A single larger prompt or a universal reranker is not supported by the measured evidence.

Published comparisons remain qualified rather than presented as a shared leaderboard:

| System | Published LongMemEval result | Published context figure | Interpretation |
| --- | ---: | ---: | --- |
| Mem0 | 94.4% | 6,787 mean tokens | Higher published accuracy and lower context than Vault; protocol details differ |
| Hindsight | 94.6% | Not paired with its headline | Higher published accuracy; context comparison is incomplete |
| Zep | 90.2% | 4,408 median tokens | Higher published accuracy and smaller reported context; median and mean are not interchangeable |
| Vault claim-first 10K | 82.0% independent judge | 8,307 mean complete reader-prompt tokens | Reproducible bounded local-first result with dual judging |
| Graphify | 76% on 50 questions | Not published | Primarily a code-graph comparator; its memory result is smaller and not protocol-matched |

Vault is not currently state of the art in hosted conversational-memory accuracy or smallest reported prompt size. Its current differentiation is local ownership, zero paid ingestion tokens in the measured pipeline, inspectable bounded evidence, strict dual-judge reporting, temporal fact history, and one workspace spanning documents, conversations, clusters, and Odin code projects.

Odin and conversational-memory benchmarks should remain separate in product claims. Odin's external Flask, Zustand, Django, and React evaluations measure project discovery, graph coverage, speed, and graph-to-model interpretability. LongMemEval and LoCoMo do not invoke Odin and measure Vault's conversational-memory retrieval and evidence pipeline.

## Promotion Rules For The Next Cycle

Future changes should be promoted only when they improve product behavior and satisfy explicit gates:

- no special-case benchmark answer logic or exposed-question tuning;
- no regression beyond declared recall, evidence-containment, token, latency, and previously-correct-answer retention thresholds;
- fresh preregistered questions for accuracy claims because the full LongMemEval set and earlier holdouts are development-exposed;
- saved per-question retrieval, packed evidence, model usage, finish reason, judge output, and failure classification;
- separate local compute/storage costs from billable API tokens;
- preserve raw authoritative evidence and citations when deterministic ledgers or reducers are used;
- keep experimental dependencies out of production until package, license, index lifecycle, resource, and clean-up behavior are proven;
- rerun clean backend, desktop, packaging, and security validation before a release-candidate label.

## July 19 CI And Push Readiness Review

The complete active working tree was reviewed before publication. The previous two GitHub CI runs on `main` had failed for three known assertions: Odin removed-source reconciliation and two tests that expected schema version 10 after schema version 11 shipped. The schema assertions now follow the current migration version. The Odin reconciliation test now verifies the durable contract—no active project membership remains—while accepting either a retained tombstone or physical cleanup after the last reference disappears. Ten repeated local runs pass both cleanup outcomes.

The local CI-equivalent validation now passes:

- quick backend tier: 196 passed;
- integration backend tier: 214 passed;
- system backend tier: 120 passed;
- benchmark backend tier: 63 passed and one optional TurboVec test skipped;
- combined backend collection: 593 passed and two intentional skips, covering all 595 collected tests;
- desktop TypeScript and Electron lint gate: 42 tests passed;
- desktop production client and SSR build: passed;
- npm audit: zero vulnerabilities;
- pinned Python contributor dependency audit: no known vulnerabilities;
- Python compilation and Odin CLI import/help smoke: passed;
- packaged helper manifest and writable-layout audit: 254 entries, no overlaps;
- Markdown/local-link/encoding and `git diff --check` validation: passed;
- repository secret-pattern review: no provider/private-key patterns; generic matches are deliberate test or smoke placeholders;
- GitHub secret scanning: zero open alerts;
- no tracked or intended new file exceeds the repository's 5 MB review threshold.

The dependency review found and fixed disclosed issues before publication. Production/development pins were advanced to compatible fixed releases for Starlette, Pydantic Settings, Cryptography, PyPDF, Pillow, NLTK, Torch, and Setuptools where each applies. The backend suite passed after installing the fixed runtime set. One upstream Starlette TestClient compatibility warning and the existing frontend chunk-size/TanStack build warnings remain non-blocking.

The CI workflow is now aligned with the incoming tree:

- GitHub-maintained actions use the current verified major releases (`checkout@v7`, `setup-node@v7`, `setup-python@v6`, and `upload-artifact@v7`);
- workflow permissions are explicitly limited to read-only repository contents;
- a dedicated dependency-audit job checks both npm and the pinned Python contributor environment;
- benchmark-analysis regressions are assigned to the benchmark tier rather than inflating the quick tier;
- push-to-main, pull-request, manual workflow dispatch, four backend tiers, desktop build, JUnit uploads, and the manual 50,000-file Odin scale gate remain covered.

The first pushed run exposed a platform-sensitive test assumption: it compared an absolute Windows source path even though Odin's canonical relationship is the normalized project-relative path. The test now resolves the source through `project_sources.relative_path`, verifies that the new active membership excludes it, and accepts either a retained tombstone or final physical cleanup. After 10 repeated local passes, the replacement GitHub run passed the quick tier and the complete automatic workflow.

`apps/desktop/public/brand/Container.svg` is a 1.6 MB SVG wrapper around an embedded
raster. It is now the canonical product wordmark for onboarding, startup, recovery,
the sidebar, and dedicated error screens. Because its size previously caused an
oversized encoded startup URL, it must remain a referenced packaged asset and must
not be embedded into generated HTML.

## July 20 Temporal Activation Isolation

The first production-path LoCoMo temporal-memory experiment used the existing 0.760586-recall@10 ColBERT trace, ingested all ten conversations into Vault's SQLite temporal ledger, retained attributed speaker names, and routed applicable questions through the production typed-evidence adapter. Infrastructure behavior was correct: all 1,540 questions completed, unsupported questions fell back, named-speaker facts retained their provenance, 34 structured contracts were injected, and measured cost remained essentially unchanged at $1.739514.

The aggregate report was not accepted as feature evidence. It showed 0.5306 official token F1, 66.82% Kimi acceptance, and 64.35% GPT-5.4 acceptance, superficially above the earlier 0.5259, 66.75%, and 63.96%. However, 1,506 questions used the unchanged fallback path and the stochastic reader regenerated 577 different hypotheses. Seven responses also ended at the length limit on the first invocation. Aggregate changes therefore conflated reader variance, incomplete retry handling, and the 34 actual feature activations.

Isolation on those 34 activations showed a clear regression. Official F1 fell from 0.6008 to 0.5419. Kimi acceptance fell from 26/34 to 21/34, a 14.71-point loss; GPT-5.4 fell from 22/34 to 21/34. Each activation added 382-1,298 characters of structured text, averaging 658.8. The router had interpreted bounded factual prompts containing preference-adjacent words—especially “favorite”—as distributed preference-synthesis requests. When requested topics did not match extracted facts strongly, the reducer retained tangential preferences instead of returning no contract.

The rejected behavior was corrected in production code rather than hidden in the benchmark. Imported dialogue may still attribute explicit first-person claims to a named speaker, but named-speaker preference routing now requires an explicit aggregate request such as a general preference query. Bounded “favorite” facts remain on ordinary retrieval. Preference contracts now abstain when the requested topic has no provenance-valid match. The subsequent `temporal-ledger-v4` hardening applies that same routing and topic scope to ordinary temporal memory selection and derived consolidation, closing the desktop packet path that previously could still admit unrelated preference items after the typed adapter abstained.

The LoCoMo runner now retries length-limited responses synchronously, increasing the allowance up to a bounded 768-token ceiling, and refuses to generate a report if any response remains truncated. A separate paired evaluator freezes an earlier activation set, reuses baseline hypotheses and judge labels whenever the corrected router falls back, and calls models only for contexts that truly change.

The corrected paired run evaluated the same 34-question set. All 34 former false positives abstained; no reader or judge API calls were made. Official F1 remained exactly 0.6008, Kimi remained 26/34, and GPT-5.4 remained 22/34. The measured regression is closed, but this is abstention and non-regression evidence rather than a new accuracy result. Another full 1,540-question temporal run is not justified until a fresh set contains genuine distributed preference-synthesis questions and the changed subset passes a preregistered paired gate.

Post-change backend verification now passes 644 tests with two intentional skips. The only warning is the existing upstream Starlette TestClient deprecation notice.

## July 20 Evolving-Memory Production Benchmark

A dedicated paired benchmark now exercises the behavior that was too sparse in the frozen 500-question LongMemEval artifact. Dataset protocol `vault-evolving-memory-v1` contains 40 deterministic cases, evenly split across current preferences, preference history, state history, and relative-date completed actions. Each case includes fourteen irrelevant sessions so the reader must distinguish the evolving fact from ordinary conversational activity. The frozen dataset SHA-256 is `ecd4e3141dc2f3772763cba57c609525b8a667207898a8440a5dcd13bf951b64`.

The paired reader protocol holds the question, Kimi K2.6 reader, GPT-5.4 independent judge, and answer rubric constant. Its baseline arm uses the prior unconsolidated claim-first packet. Its candidate arm creates a real temporary Vault database, inserts the conversation sessions and messages, runs production temporal synchronization, retrieves through `get_context_memory`, evaluates the runtime typed-evidence adapter, and injects a bounded contract only when the production path supports it. Deterministic required-fact groups provide a second scorer independent of the LLM judge.

The first smoke exposed two product-path serialization defects rather than hiding them. Resolved relative action dates were stored correctly in `valid_from`, but model-facing detail included both that date and the source word “yesterday”; Kimi could apply the offset twice. Temporal items now present the resolved date in model-facing prose while retaining the exact relative source quotation separately as immutable citation metadata. State-history questions using “before ... now” were not recognized as history requests; the history selector now includes explicit “before” wording and returns dated superseded/current state evidence. Both behaviors have dedicated regression tests.

The final v3 run completed 80 reader/judge arms across all 40 cases with no scorer disagreement:

| Measurement | Legacy claim-first | Production temporal path | Change |
| --- | ---: | ---: | ---: |
| GPT-5.4 judged accuracy | 40/40 (100%) | 40/40 (100%) | No regression |
| Deterministic accuracy | 40/40 (100%) | 40/40 (100%) | No regression |
| Mean reader prompt tokens | 774.725 | 181.250 | **-76.60%** |
| P95 reader prompt tokens | 788 | 276 | **-64.97%** |
| Total reader prompt tokens | 30,989 | 7,250 | **-76.60%** |
| Mean context characters | 1,907.12 | 403.88 | **-78.82%** |
| Estimated uncached reader cost | $0.033248 | $0.010087 | **-69.66%** |

Every category scored 10/10 in both arms. The combined v3 evaluation used 38,239 Kimi prompt tokens and 1,752 Kimi completion tokens across both arms, plus 10,164 GPT-5.4 judge prompt tokens and 320 judge completion tokens. Estimated cost was $0.043335 for Kimi at uncached rates or $0.020368 with reported caching, plus $0.030210 for GPT-5.4 judging. The cache-adjusted total was $0.050578; the all-uncached estimate was $0.073545.

This experiment is a controlled capability and efficiency result. It establishes that the production ledger can preserve answer quality while substantially shortening evidence for the four explicitly covered fact families. It does not establish general conversational-memory accuracy, market leadership, or performance on arbitrary multi-hop questions. The suite and runner live in `scripts/backend/generate_evolving_memory_benchmark.py` and `scripts/backend/evaluate_evolving_memory_api.py`; generated datasets, checkpoints, logs, and reports remain under `.tmp/vault-odin-memory-benchmark`.

The production changes behind the result are broader than benchmark prompt tuning. Shared source-verbatim claim semantics now serve both ingestion and bounded evidence packing. Preference reduction selects the latest cited current fact per normalized topic and admits earlier versions only for explicit history questions. Current preference and advice paths exclude superseded rows. Safe day-level expressions resolve relative to the source timestamp for completed actions, while coarse ranges remain declared metadata. Imported dialogue of the form `Name said, "..."` can attribute explicit first-person claims to that named subject without converting assistant suggestions into user actions. These behaviors preserve original citations and fall back whenever the structured contract is unsupported or insufficient.

The subsequent LoCoMo activation audit narrowed the production boundary further. Surface words such as “favorite” are not sufficient evidence that a question requests distributed preference synthesis. Named-speaker routing now requires an explicit aggregate preference request, and topic matching must find provenance-valid evidence or abstain. `temporal-ledger-v4` records this routing contract across both the typed adapter and the shared chat/Bridge memory packet. The evolving-memory suite remains the current positive controlled result; the corrected LoCoMo paired run remains a neutral typed-contract abstention result, supplemented by a deterministic production-bundle regression for the shared packet path. Both are required context for future temporal-memory promotion decisions.

Current benchmark artifacts and protocol responsibilities are:

- `evaluate_vault_locomo_api.py`: full retrieval/reader/dual-judge evaluation, optional production-temporal routing, persistent dialogue ledger, named-speaker ingestion, synchronous bounded length retry, and report blocking on unresolved truncation;
- `evaluate_locomo_temporal_paired.py`: frozen activation-only comparison that reuses unchanged hypotheses and judgments, checkpoints only changed paths, and reports paired wins/losses and incremental cost;
- `evaluate_evolving_memory_api.py`: paired legacy-versus-production evaluation for explicit evolving-fact families;
- `generate_evolving_memory_benchmark.py`: deterministic generation and hashing of the 40-case controlled corpus.

The promotion state is therefore precise: explicit evolving preferences, state histories, and relative action dates pass their controlled product-path regression gate; broad LoCoMo preference routing failed and was removed; conservative fallback is verified; positive distributed synthesis still needs a fresh preregistered evaluation set before another full paid LoCoMo temporal run.

## July 21 Atomic-Memory Readiness And Offline Evaluation

The architectural hypothesis was that Vault leaves accuracy on the table by asking the query-time reader to extract, attribute, date, deduplicate, and synthesize raw session text simultaneously, whereas systems such as Mem0 perform much of that work during ingestion. The atomic-memory work therefore moved question-independent fact compilation to write time and required the query path to activate only when an operation-specific evidence contract proves completeness.

The production-shaped compiler now retains a lossless source envelope plus deterministic semantic facts with speaker, session, turn, observation/event dates, quantities, state/supersession identity, and immutable source citations. Every source unit has a terminal `facts_extracted` or `processed_no_fact` outcome and a content hash. The question-only planner reads no benchmark question-family label; it plans current-state, state-comparison, list/count, numeric, temporal-difference, or event-order operations from ordinary question text and retrieved-session count.

The evaluation infrastructure was hardened before further paid work. Coverage, reader, and judge stages use content fingerprints; impact-only replays merge unchanged rows; packet diffs identify exactly which reader inputs changed; reader and judge checkpoints invalidate only when their own inputs change. Local neural benchmarks are CUDA-fail-closed on the RTX 3060 Laptop GPU using PyTorch 2.12.0+cu130. Deterministic JSON parsing and contract evaluation remain CPU work because they invoke no neural model. A cache-version failure during v6 proved that fact-cache schema versions must advance whenever compiled fact semantics or unit typing changes; v7 performs that invalidation.

The development sequence matters:

- The earlier v4 baseline safely activated 3/200 representative and 2/200 former-final questions.
- v5 added source-unit accounting, grouped-number parsing, grammatical quantity subjects, date/state normalization, unit-family filtering, repeated-event deduplication, and evaluation-only deterministic reference checks. It reached 4/200 on both sets with zero false-safe activations.
- An initially permissive v6 explicit-cardinality rule transiently activated 10/200 and 8/200, but produced three false-safe operations on each set. Local counts were being mistaken for cross-session totals. Those results were rejected rather than promoted.
- Tightening context coverage, related-cardinality history checks, and later-related-fact checks restored zero false-safes. Current-state selection was then restricted to the requested concept and supersession chain, adding one valid former-final activation for the current BBQ-sauce state.
- A clean full replay exposed an aquarium failure: three tank-capacity values were added as fish counts, producing 50 instead of 17. Gallons/liters are now a separate capacity family. Because the implicit singular pleco still is not an explicit count fact, the final system safely falls back instead of inventing the missing operand.

The clean atomic-memory v7 results are:

| Metric | Representative 200 | Former-final 200 |
| --- | ---: | ---: |
| Stored evidence recall | 98.1763% | 98.4709% |
| Packed evidence recall | 86.6261% | 84.7095% |
| Atomic candidates | 119 | 117 |
| Reference-verified safe activations | 4 (2.0%) | 5 (2.5%) |
| False-safe activations | 0 | 0 |
| Activated-question completeness | 100% | 100% |
| Deterministic result correctness | 4/4 | 5/5 |
| Source-unit compiler coverage | 100% | 100% |
| Temporal anchor recall | 98.1132% | 100% |
| Direct-fact recall | 100% | 100% |
| Expected mean prompt tokens | 8,283.92 vs 8,290.75 control | 8,303.97 vs 8,320.81 control |

No reader or judge API calls were made. All gates pass except the preregistered 10% activation/usefulness threshold, so the machine-readable decision remains `no-go`. Running a large reader evaluation now would mostly repeat the claim-first control and would not establish an atomic-memory accuracy gain.

The remaining blockers are semantic rather than retrieval-budget problems:

- implicit cardinality and entity normalization, such as turning “a small pleco” into one cited fish entity without unsafe inference;
- closed-world category membership for genuine “how many different/all” questions;
- progressive and cumulative counters that require identity-aware histories rather than summing snapshots;
- repeated-event identity and deduplication across paraphrases and sessions;
- broader but conservative current-state and supersession normalization;
- coreference, synonyms, and category words absent from the source wording while retaining exact provenance;
- a fresh promotion corpus, because both 200-question manifests are development-exposed and only seven LongMemEval questions remain eligible and untouched under the current rules.

The next gate is unchanged: reach at least 10% safe activation on both development sets with zero false-safe operations, 100% source-unit accounting, and prompt usage below the claim-first control. Only then should a new frozen corpus receive reader and dual-judge evaluation.

## July 22 Local Semantic Ingestion Experiment

An opt-in local-model enrichment tier is now production-wired after deterministic chat
memory sync. It runs as a low-priority, preemptable job, refuses non-loopback LLM
endpoints, stores validated facts in separate versioned session state, and marks that
state stale when source content changes. Bounded overlapping chunks preserve full
session hashes and original turn citations; malformed or unsupported citations are
discarded before persistence. Deterministic memory remains the fallback and source of
record.

The first Qwen3 4B Q4_K_M CUDA pilot targeted the frozen three-session doctor-count
case. User turns took 343.40 seconds total and yielded 36 valid facts, seven overlap
duplicates, and one genuinely invalid excerpt. The model generated useful concise
visit/specialist facts, but no `entity_category` qualifiers and at least one incorrect
completed-visit interpretation. Combined packing used 107 facts / 8,498 estimated
tokens versus 139 / 8,341 for deterministic-only, and both arms still failed the
`closed_world_category_coverage` slot. This supports continued small-fixture
development, not promotion or a large reader/judge benchmark. Full assistant-turn
enrichment is substantially slower on verbose benchmark sessions and remains
idle/background work.

## July 22 API Semantic Extraction Recovery/Control Smoke

The benchmark runner now performs bounded, resumable, provenance-validated cloud
extraction while the production path remains loopback-only. A 12-question set was
frozen from already-exposed evaluation data with one claim-first failure and one control
per LongMemEval family. GPT-5.4 processed all 120 retrieved sessions in 270 requests,
producing 4,089 valid facts and 187 rejected candidates for an estimated $8.7551.

Coverage did not clear the offline gate: 100% stored evidence recall, 92.8571% packed
evidence recall, zero false-safe packets, but 0/12 safe atomic activations and a larger
mean packet than claim-first. The facts-only reader nevertheless moved from 6/12 to
7/12 dual-judge correctness, with three wins and two losses (McNemar p=1.0). The gains
covered current-value update, preference recommendation, and temporal calculation. The
losses exposed over-broad project identity and a table relationship reduced to an
incomplete Sunday assignment. Two of six controls regressed, so promotion failed.

This is evidence that write-time synthesis can help the reader, but not that a flat
fact store is sufficient. The next semantic compiler must preserve structured
relationships, normalize entity/category identity, prove closed-world set coverage,
and reject loosely related actions before a larger API extraction run is justified.

## July 24 Open RAG External-Corpus Validation

Vault completed retrieval for all 3,045 questions in Vectara Open RAG Bench at frozen dataset revision `63f6b052ff83508b08e242db42263ee708815c26`. Section Hit@1 was 0.640394, Hit@5 was 0.901149, Hit@10 was 0.948440, and document Hit@10 was 0.996059. Mean query latency was 1.0597 seconds and P95 was 1.0648 seconds. Plain-text section Hit@10 reached 0.975444; text-image, text-table, and text-table-image reached 0.899083, 0.912162, and 0.909091. The result establishes strong external document discovery while identifying multimodal section ranking as the clearest retrieval weakness.

The paid QA run used a deterministic first-500 prefix as an explicit spending gate and remains paused before the remaining 2,545 questions. Kimi accepted 419/500 answers (83.8%, Wilson 80.31%-86.77%); GPT-5.4 independently accepted 368/500 (73.6%, Wilson 69.57%-77.27%). Agreement was 86.2% and Cohen's kappa was 0.5947. No reader response was length-limited.

The reader consumed 1,336,031 input and 80,768 completion tokens: 2,672.1 prompt tokens and 2,833.6 total reader tokens per question. Including both judges, recorded usage was 3,357.6 tokens/query. The recorded component estimates sum to $1.910226: $1.428372 reader, $0.130869 Kimi judge, and $0.350985 GPT judge. A legacy aggregate field in the artifact incorrectly remained zero; public documentation uses the component sum.

This is a separate workload from LongMemEval. Open RAG's 2,672.1 prompt tokens/query is numerically 67.8% below LongMemEval claim-first's 8,307.1, but the corpus, question structure, and packed evidence differ. It is therefore a new document-QA efficiency measurement, not a valid cross-benchmark optimization delta. The full retrieval score is publishable; QA must remain labeled as a frozen 500-question prefix pilot.

## July 24 UI Distillation And Verification

The first implementation pass converted the earlier UI backlog into verified reductions. Home activity hierarchy and OCR settings wrapping were normalized. Map now exposes authoritative links, unclustered items, reset behavior, and large-vault mock coverage. The redundant cluster-detail right rail and nonfunctional close button were removed; cluster rows now navigate directly; duplicate cluster-local Map and source/status surfaces were removed. Global Saved chats, the Settings utility rail, the unused legacy `ClusterMap`, 29 unused UI primitives, and a stale Figma export utility were also removed.

The browser audit passed 46 TSX interaction checks and rendered 13 routes at 1440x900 and 768x900, plus the cluster route at 512 px, without page-level overflow, unlabeled controls, browser errors, or failed close/reset interactions. Remaining work is intentionally narrower: source-inspector persistence, stale embedded project/search/chat paths, Bridge and Settings decomposition, keyboard and automated accessibility, 200% zoom, locked/offline behavior, and packaged Electron validation. `docs/UI_RECOMMENDATIONS_BACKLOG.md` tracks the remaining work.

## July 29 Deep-Audit Remediation Status

The active audit implementation now has end-to-end foundations for atomic
cluster membership, transcript isolation, typed and resumable background work,
partial import reporting/retry, adaptive metadata scheduling, durable chat
generation, model discovery/recovery, evidence-gated TurboVec activation, and
retrieval of unclustered sources. These paths preserve source authority and
degrade optional enrichment independently from search and ingestion.

Odin project freshness is now a layered, versioned contract. Git projects
combine baseline-to-HEAD, staged, unstaged, untracked non-ignored, deleted, and
rename-side paths into one bounded delta. Delta application reads and embeds
only those paths, retains unchanged identities, publishes retrieval atomically,
and exposes the old structure snapshot as stale. Full rebuilding is an
explained fallback, not the ordinary sync action. Project answers now return
evidence roles, snapshot IDs, freshness, limitations, and bounded authority.

Rendered desktop verification found zero collisions with the measured
window-control exclusion at 1024×680. The import overlay can be dragged across
the viewport and remembers a normalized position. A live reload initially
reset that position; the portal lifecycle dependency was corrected and the
rendered retest retained `(229, 171)`. Browser-extension selection, tab,
transport, upload-size, and token-rotation boundaries have focused regression
coverage. The next pass covers remaining Settings/recovery structure,
accessibility and zoom, diagnostics, then the complete regression/build gates.

Diagnostic bundle format v2 now excludes raw logs and privacy-filters paths,
prompts, messages, credentials, recovery material, and unstructured worker
errors. It keeps bounded counts, error codes, diagnostic IDs, and runtime
capabilities. Focused testing exposed an upgrade-only startup defect where the
chat-generation request index preceded its column; startup now adds the column
first and a legacy-schema regression protects the order. The CI contract also
now includes extension unit checks, rendered desktop Playwright geometry and
drag persistence, renderer security, control auditing, Ruff, compilation, and
an explicit opt-in packaged Windows smoke job.

The Settings loader no longer polls all domains from every tab. It loads only
the visible section and never starts model discovery implicitly. The rendered
suite now verifies wrong-passphrase feedback and focus, model-loss visibility,
200% text with reduced motion, minimum-size chrome exclusion, and persisted
import dragging. Source folder groups now have a bounded, searchable server
contract with `total`, `offset`, and `has_more`, preventing large collections
from becoming an unbounded metadata response.

The metadata audit confirmed why large imports could remain with raw-looking
descriptions even after indexing: production source enrichment explicitly
disabled model use. Source processing is now progressive instead of blocked or
misrepresented. Tier one produces bounded deterministic metadata immediately;
tier two is a resumable, content-hash-guarded local-model job that publishes a
semantic description later and refreshes organization. Metadata quality is
explicit in schema/API/UI, upgraded vaults receive migration 25, and model loss
blocks only tier two while automatic recovery wakes it.

First-hand Odin execution verified the expanded delta-oriented command surface
but exposed launcher approval drift as an unactionable authentication failure.
Odin now emits a plain repair-and-pair explanation and stable machine fields
for that state. The product plan keeps executable fingerprint binding, requires
approval for replacement, adds an idempotent combined repair flow and
`odin doctor`, and presents only a bounded changed-path inbox. Ordinary
freshness checks remain revision/status probes and never crawl or restructure
the full project tree.

The focused gate after these changes passed four metadata/migration/Odin
backend checks, the semantic model-prerequisite recovery check, desktop
typechecking, 148 Electron behavior checks, six real-browser recovery and
geometry flows, 24 extension checks, renderer/control/lockfile audits, and
Python compilation. Local Ruff execution is currently unavailable because the
tool is absent from this virtual environment; CI installs and runs it, and the
final environment sweep must preserve that gate.

A follow-up interaction and scale scan found two native confirmation prompts
and a full-vault cluster-destination traversal. Both are removed. Destructive
or high-impact actions now use the application confirmation surface, while
source move and cluster merge destinations use bounded, escaped server-side
search. This keeps modal behavior consistent and avoids hydrating every
cluster merely to populate a select control.

Odin's planned diagnostic contract is now partially delivered:
`odin doctor` inspects launcher/runtime/approval health without listing or
reading projects. Its live JSON result in this pass identified the changed
development executable as `repair_needed` with the stable next action
`repair_and_pair`, demonstrating that launcher trust drift can be explained
without weakening the executable binding.
