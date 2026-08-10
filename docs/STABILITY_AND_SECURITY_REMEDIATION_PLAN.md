# Stability and Security Remediation Plan

## Implementation checkpoint (2026-08-10)

Implemented and regression-tested in the current working tree:

- Phase 1 authorization fixes, including Bridge intersection scope, full citation scanning,
  atomic pairing, approval compatibility, explicit legacy scopes, redacted history, Defender
  retry/fallback/sandbox policy, Bridge client optimistic concurrency, and read-only recovery GET.
- Generation and job leases, hard deadlines, stale recovery, one-active-generation enforcement,
  durable cancellation, route ownership guards, restartable migration metadata, and scoped-delete
  cancellation.
- Watched-folder failure backoff/action-needed state, root-scoped reconciliation, paused-job dedupe,
  and security-scan schedule ownership.
- Extension request deadlines, bounded CLI response reads, Odin session renewal/run timeout, and
  credential reload on tunnel reconnect.
- Pagination-preserving chat/task polling, poll abort ownership, backend-token generation
  invalidation, graph seed capacity fill, blockwise exact-vector fallback, and paged complete-analysis
  scanning.
- Managed-model swaps now publish a verified replacement before draining requests pinned to the
  previous runtime, with an enforced drain deadline and rollback that keeps a working old runtime.
- Attachment retrieval now ranks bounded metadata candidates and decrypts only final winners; LCOV
  and Git history ingestion enforce byte/time/record limits and use streaming or batched processing.
- A bounded maintenance coordinator now prunes terminal jobs/generations, stale retrieval data,
  expired CLI sessions, and aged audit rows without automatic `VACUUM`.
- Command-palette lookup is bounded server search with debounce/cancellation; Home, Timeline,
  Bridge, and the palette invalidate stale work on backend/vault generation changes. Pending chat
  handoffs and Odin-pairing notification identities are TTL/bound managed.
- Large content-encryption resumptions no longer run to completion on the unlock request. The vault
  remains explicitly non-ready while a cancellable batch migration evacuates plaintext, reports
  status, and safely resumes after lock/restart; small migrations retain bounded compatibility.
- Scanned-PDF OCR is deferred out of parser subprocesses into the scheduler-owned `ocr_cpu` stage,
  with source checksum validation before OCR publication. Dynamic browser ingestion retains its
  isolated-process boundary while enforcing two-worker admission and fail-fast overload behavior.
- Source cleanup now reference-checks and removes encrypted quarantine originals; scheduled
  maintenance prunes unattached passed/failed quarantine records on separate bounded recovery
  windows. Storage reports shared SQLite allocation separately from vault-attributable sidecars,
  encrypted blobs, and estimated logical payload bytes.
- Setup-state read/merge/write is serialized by a crash-recoverable filesystem lock, supports
  revision compare-and-swap, and retains atomic replacement so concurrent renderer callbacks do
  not silently discard one another.
- Embedding transitions now stage target-model chunks alongside the still-searchable active tuple,
  refuse publication until every searchable source has target coverage, atomically switch the
  selector, retain the previous tuple for rollback, and queue per-vault sidecar rebuilds. Bounded
  maintenance prunes chunk tuples no longer referenced by active/previous/building policy.
- Long chat timelines and project/map side panels are virtualized with measured rows and bounded
  overscan. Force-graph runtimes are loaded only for graph mode and explicitly destroyed on hide or
  unmount; the rendered 241-message navigation flow passes without console errors.
- Onboarding library creation now has a durable `prepared` â†’ `created` â†’ `path_set` â†’
  `setup_complete` journal. Stage updates are monotonic and serialized, retries are idempotent, and
  resume refuses a directory whose canonical filesystem identity changed between stages.
- Temporal synchronization detects append-only histories and extracts only new turns, unchanged
  atomic-memory compilations are skipped, and stale fact retractions are batched. Chat transcript
  indexing keeps a cumulative bounded user-memory summary plus the latest 40 messages and performs
  no reindex work for an unchanged message generation.
- Cluster merges commit at most 100 planned sources/chats per transaction, persist cursors and moved
  identities, resume after interruption, absorb late members before final deletion, and use
  compare-and-swap rollback so a later user move is reported as a conflict rather than overwritten.
- Dynamic browser ingestion uses a supervised two-process pool with a fresh isolated context per
  URL, fail-fast admission, parent/child network validation, and 25-request worker recycling.
- Exact-vector snapshots and immutable Turbovec sidecars use byte-bounded epoch-keyed caches.
  Maintenance atomically retires aged non-current sidecar epoch directories while protecting the
  active epoch and recovering interrupted deletion names.
- Chat timeline GET is read-only again: it no longer cancels scoped jobs or converts retriable
  generations to stopped. Disabled Bridge requests with a previously valid credential retain the
  authenticated `403 bridge_disabled` contract.

The implementation rows below are complete in the current working tree. The only mandatory
qualification still requiring elapsed wall-clock time is the 72-hour mixed-workload soak. A clean
VM install remains intentionally deferred by owner direction and must not be represented as passed.

Current local evidence:

- backend quick tier: **624 passed, 16 intentionally skipped, 440 deselected**;
- backend integration tier: **232 passed**;
- backend system tier: **140 passed**;
- backend benchmark tier: **67 passed**;
- focused integration/watch gate: **190 passed**;
- desktop TypeScript plus Electron lint/unit gate: **189 passed**;
- browser extension: **24 passed**;
- rendered Playwright long-chat/Markdown/citation flow: passed with console checks;
- explicit scale gates passed: 1m-chunk exact search (**7.343s**, **2.9 MiB** RSS delta),
  100k-source root reconcile (**0.154s**, **1.3 MiB**), 5k watched files (**5.217s**,
  **1.2 MiB**, 20 batches), Odin 50k scale (**66.852s**, **68.3 MiB**), and MCP 1000-call
  soak (p95 **57.122ms**, zero observed RSS growth);
- a fresh packaged Windows directory passed runtime, Electron launch, full-vault semantic/OCR/cache,
  migration recovery, Defender policy, UI, Odin, and startup-p95 checks;
- the NSIS installer passed local explicit-directory install/uninstall lifecycle validation;
- the accelerated mixed-workload soak harness passed 21 cycles with 21 sources, 7 chats,
  3 lock/unlock cycles, 2 backend restarts, and zero operation/invariant failures;
- production dependency audit: **0 vulnerabilities** after updating transitive `nanoid` to 3.3.17;
- `git diff --check`: passed (line-ending conversion notices only).

### 72-hour soak operation

The soak is an elapsed-time release qualification, not a test that needs an interactive agent. It
runs a real isolated backend and repeatedly mixes source creation/indexing, semantic retrieval,
chat/session pagination, watched-folder refresh, project sync, Bridge context calls, job processing,
lock/unlock, and backend restarts. It checkpoints after every cycle, records latency and resource
growth, checks SQLite integrity and queue/generation invariants, and resumes from the same isolated
state after runner interruption. A short run validates the workload but does not satisfy the
72-hour gate.

Start it from the repository root:

```powershell
.\scripts\backend\start-remediation-soak.ps1
```

Monitor it without attaching to the runner:

```powershell
.\scripts\backend\monitor-remediation-soak.ps1
```

The live checkpoint is `.tmp/remediation-soak/live-status.json`; the terminal qualification report
is `.tmp/remediation-soak-report.json`.

This plan consolidates the validated code-review findings from the security, upgrade,
long-session, scale, integration, desktop, and lifecycle passes. It is intentionally
ordered by invariant and dependency rather than by file, so fixes do not mask one
another or introduce incompatible database and API behavior.

## Delivery rules

- Preserve secure defaults. Compatibility paths must be explicit, observable, and deprecated.
- Add a failing regression before or with every fix. Concurrency defects require real multi-connection tests.
- Bound work at admission and execution: bytes, records, time, retries, queue depth, and memory.
- Make state transitions conditional (`WHERE status = ...`) and transactional.
- Schema changes must be forward-only, restartable, and tested from both clean and populated databases.
- UI async work must have ownership (route/vault/request generation) and cancellation where possible.
- Retention deletes only terminal or expired data, in bounded batches, with foreign-key behavior tested.
- Roll out expensive behavior changes behind metrics or feature flags until scale gates pass.

## Phase 1 — security and authorization invariants

| Finding | Fix invariant | Required regression / rollout gate | Status |
|---|---|---|---|
| Bridge vault/cluster allowlist bypass | Vault-only and cluster-only clients remain supported; when both lists exist, every read, expansion, and write must satisfy both. SQL and value checks share the same semantics. | HTTP tests for matching scope, wrong vault/right cluster, right vault/wrong cluster, unclustered requests, list endpoints, expansion, and every write tool. | Fixed; HTTP matrix passing |
| Synthesis checks only first six citations | Scan every citation admitted to model input for hostile instructions. Presentation summaries may remain bounded. | Hostile seventh citation; maximum packet count/size performance test; assert model adapter is not called. | Fixed; focused test passing |
| Extension pairing can be approved twice | Pairing claim, client insert, token hash, terminal status, and audit commit in one `BEGIN IMMEDIATE` transaction. | Two-connection barrier test yields one credential and one 409; injected failure leaves no client and pairing retryable. | Fixed; concurrency test passing |
| Approval polling query parameter regression | Prefer header; temporarily accept deprecated query parameter with identical one-time delivery behavior. | HTTP tests for header/query, header precedence, missing/invalid code, expiry, one-time token delivery; remove query only in a later major version. | Fixed; compatibility tests passing |
| Empty-scope upgrade disables integrations | Freeze legacy allow-all clients to explicit IDs of vaults present during migration. Disable only if no safe vault exists. Never grant future vaults automatically. | Populated upgrade tests with one/many/no vaults, cluster-only clients, explicitly disabled clients, and rerun idempotence. | Fixed; upgrade/idempotence tests passing |
| Bridge request history stores `mode` as `query` | Store encrypted query when a vault key exists; otherwise store an empty/redacted query. Keep mode only in its field. | Secured/unsecured/no-vault rows; locked-vault reads; database byte scan for plaintext secret. | Fixed; focused test passing |
| Defender unavailable blocks imports | Keep fail-closed default. Classify transient/unavailable/permanent results, use bounded retry with jitter, detect supported Defender fallbacks, and expose an explicit warned sandbox-only policy. | Mocked Defender result matrix, retry exhaustion, restart recovery, policy audit, and packaged Windows smoke. | Fixed in code/tests; packaged Windows smoke remains a release gate |
| Bridge optimistic update omitted by desktop | Send `expected_updated_at`; on 409 reload and present conflict instead of overwriting. | Two-window edit test and stale-write HTTP test. | Fixed; stale-write tests passing |
| GET recovery drill mutates live generations | Split inspection (`GET`) from mutation (`POST`); recovery only affects rows older than heartbeat cutoff. | GET is read-only; fresh row untouched; stale row transitions once; concurrent completion wins safely. | Fixed; recovery and timeline GET regressions passing |

## Phase 2 — jobs, generations, migrations, and cancellation

| Finding | Fix invariant | Required regression / rollout gate |
|---|---|---|
| Job timeout metadata is not enforced | Persist claim/heartbeat/deadline. Reclaimer conditionally moves expired running jobs to retryable/failed, releases dedupe, and records timeout reason. Worker completion must use claim token so a reclaimed worker cannot overwrite the new attempt. | Fake-clock unit tests, two-worker race, process-kill integration test, retry budget, and long valid job heartbeats. |
| Stale `in_flight` generation blocks synthesis jobs | Add generation heartbeat and lease owner; conflict checks ignore/recover only lease-expired rows. | Fresh generation blocks; stale generation recovers; late original writer cannot complete; restart and mid-session recovery. |
| Multiple active generations per chat | Add a database-enforced active-generation guard (partial unique index or transactional session lease). Return/reuse idempotently by request ID. | Simultaneous starts across connections; distinct request IDs; retry of same request; terminal state releases slot. |
| UI Stop only closes SSE | Add authenticated server cancellation that marks the generation cancelled and propagates a cancellation token through retrieval/model/save stages. Never save a completed assistant answer after cancellation wins. | Cancel before claim, during retrieval, during streaming, and at completion race; restart persistence; UI status test. |
| Route change can update wrong chat | Abort stream on chat ID change and guard every post-await update by route/request generation. | Delayed stream while switching A→B; retry timer after navigation; unmount warnings; back navigation. |
| Migration `running` row bricks startup | Store lease/heartbeat and migration metadata. On startup, auto-retry only explicitly restartable migrations; otherwise enter recovery mode with backup/repair action. | Kill at each migration checkpoint, resume, non-restartable quarantine, backup restore, repeated startup. |
| Long encryption migration blocks unlock | Make migration resumable in bounded batches after key verification, report progress, and allow safe pause/resume without exposing plaintext. | Large-vault timing, lock during batch, crash/restart, disk-full, and cache preservation policy. |
| Deletes leave scoped work running | In the deletion transaction, cancel queued/retryable jobs and request cancellation of running jobs before deleting chat/project/cluster/source state. | Delete during each job stage; late worker completion; FK cascades; recreate same ID/scope. |
| Model swap kills in-flight chats | Drain old runtime with a deadline while new requests route to the new runtime; force-stop only after drain timeout. | Swap during one/many streams, failed new runtime startup, rapid toggles, memory ceiling. |

## Phase 3 — schedulers and integrations

| Finding | Fix invariant | Required regression / rollout gate |
|---|---|---|
| Watched-folder error retry storm | Advance schedule on failure using persisted exponential backoff plus jitter; reset after success; cap attempts and surface action-needed state. | Missing/permission-denied path, backend restart, clock jump, recovery, and no more than configured attempts. |
| Watch reconcile reads whole vault | Query only sources belonging to the integration/root using indexed normalized membership; page results. | 100k-vault/100-file-root query-plan and memory test; rename/case/symlink boundaries. |
| Up to 5000 files monopolize import slot | Split discovery from bounded import batches; checkpoint cursor and yield between batches; enforce per-integration/global queue budgets. | 5k files plus interactive import fairness, restart resume, duplicates, directory churn. |
| Security schedule advances on deduped stuck job | Advance `next_run_at` only when a new scan is claimed or a scan completes; surface existing job state separately. | Due + queued/running/stale/failed combinations and restart. |
| Locked watch remains perpetually due | Record blocked-by-lock state and next retry/backoff without pretending success; trigger catch-up on unlock. | Repeated nightly lock/unlock and long lock interval. |
| Paused job invisible to dedupe | Include paused jobs in dedupe ownership unless the job type explicitly permits replacement; define resume/cancel semantics. | Pause while scheduler fires; resume; cancel then enqueue. |
| Embedding readiness creates reconcile waves | Maintain one coalescing reconcile intent per vault/index epoch and release jobs according to global queue capacity. | Rapid ready/not-ready toggles, 100k sources, worker restart, epoch supersession. |
| Extension captures create reindex flood | Coalesce by source to newest generation and apply per-client/global admission budgets. | Rapid recapture of same/different sources, fairness, final generation indexed. |
| CLI session expires during long project run | Refresh/renew session while polling and enforce a configurable wall-clock timeout with progress-aware messaging. | Run beyond 15 minutes, refresh failure, backend restart, terminal timeout. |
| Extension fetch has no timeout | Use AbortController deadlines and bounded backoff; prevent overlapping retries. | Hung socket, offline/online transition, popup close, service-worker suspension. |
| Tunnel reconnect uses stale token | Read current credential for every reconnect or subscribe to rotation; invalidate old credential atomically. | Rotation while connected/disconnected, restart, rollback on failed rotation. |

## Phase 4 — scale and memory bounds

| Finding | Fix invariant | Required regression / rollout gate |
|---|---|---|
| Exact vector search materializes full dense vault matrix and caches eight | Search sidecar/shards in bounded blocks with top-k merge. Cache byte budget, not vault count; invalidate by index epoch. | 100k/1m synthetic chunks, peak RSS gate, stale sidecar fallback, concurrent vaults, ranking parity. |
| Complete analysis loads full decrypted corpus | Stream/page chunks into a bounded reducer with cancellation and progress; never hold full plaintext corpus. | Large secured vault, peak RSS, lock/cancel mid-run, deterministic output sampling. |
| Attachment retrieval decrypts all chunks before cap | Rank/filter metadata first, fetch/decrypt only bounded winners, and cap attachments/chunks/bytes. | Many large attachments, secured vault, mixed relevance, cancellation, query count. |
| LCOV import reads/materializes entire file | Enforce byte/line/record limits while streaming; batch DB writes and reject pathological records. | Oversize file, huge line, malformed partial input, disk-full, 1m records. |
| Git intelligence captures huge `git log --numstat` | Bound commits, output bytes, files, subprocess time, and parse incrementally; mark truncated results. | Huge monorepo/history, binary paths, malicious names, timeout, cancellation. |
| Chat memory rebuilds/decrypts/re-embeds whole transcript | Incremental summaries and embeddings keyed by message generation; bounded recent window; reuse cluster-independent work. | Long thread, edited/deleted messages, secured vault, multi-cluster fanout, memory/RSS gate. |
| Grounded transcript/context can grow | Keep token/byte budgets at every caller and assert final prompt size immediately before model invocation. | Mixed attachments/memory/citations, tokenizer mismatch, fallback model limits. |
| OCR runs inside parser pool | Route OCR through its own bounded semaphore/job stage; parser releases capacity while waiting. | Bulk scanned PDFs plus text imports, CPU/RAM ceilings, cancellation. |
| Browser ingestion spawns one Chromium per URL | Reuse a supervised browser pool with bounded pages and per-page timeout/memory recycling. | URL burst, crash, hostile page, leaked page, restart. |
| Vector activation is not coordinated with reindex | Publish embedding policy/index epoch only after minimum usable index is ready; dual-read or explicit rebuilding state during transition. | Model switch, rollback, crash, mixed dimensions, search during rebuild. |
| Sidecar reloads per search | Cache immutable mapped sidecar by epoch with byte-bounded eviction and atomic publication. | High-QPS search, rebuild during reads, file replacement on Windows. |
| Temporal fact sync is quadratic | Diff new/changed messages, batch candidates, index lookup keys, and cap one transaction. | Long chats, repeated no-op sync, concurrency, rollback. |
| Cluster merge holds long SQLite write lock | Plan/read outside transaction; apply bounded conditional batches or maintenance mode with resumable journal. | Thousands of sources, concurrent reads/writes, rollback, interruption. |
| Graph view stops after balanced quota | Keep balanced seed floor, then fill remaining capacity from global ranking. | Single/multi-term queries, duplicate candidates, exact capacity, deterministic order. | 

## Phase 5 — frontend long-session correctness

| Finding | Fix invariant | Required regression / rollout gate |
|---|---|---|
| Chat/tasks polling replaces loaded pages | Poll first page and merge by ID while preserving older pages and stable ordering; reset only on explicit filter/vault change. | Load older → poll → items remain; updates/deletes; cursor invalidation; 10k-row render behavior. |
| Poll work applies after unmount/section change | Hook owns AbortController/request sequence; cleanup invalidates results; callbacks use functional updates. | Delayed response after unmount/section/vault change. |
| Backend token cache survives URL/restart change | Invalidate token and in-flight resolution on backend URL/generation change; reacquire before authenticated calls. | Backend restart, vault move, HMR, two windows, safeStorage transition. |
| Health/poller bursts after visibility changes | One shared visibility-aware coordinator, deduplicated health request, jitter, and immediate-only-if-stale resume. | Repeated alt-tab/sleep-wake, many subscribers, offline recovery. |
| Import progress polls when idle | Poll only while active/recent or use shared event/status coordinator. | Idle network count, active cadence, completion, unmount. |
| Map request race | Route/vault/query generation guard plus cancellation; latest request exclusively owns state. | Slow A then fast B, vault switch, error after success. |
| Projects load-more races refresh/vault switch | Cursor request tied to dataset generation; dedupe by ID; ignore stale append. | Refresh/load-more overlap, vault change, deletion/update between pages. |
| Semantic search filters only first 24 and hides failures | Server-side filters and cursor pagination; clear/mark stale results on errors. | Filter beyond first page, retry/error state, changing query, large dataset. |
| Command palette fetches/renders 500+500 | Debounced server search with small limit, pagination, virtualization, and request cancellation. | 100k sources/clusters, rapid typing, keyboard navigation, memory/DOM gate. |
| Home/Timeline/Bridge keep stale vault | Central vault-generation subscription; all requests and caches keyed by vault. | Move/switch vault while mounted and with slow requests. |
| Notifications mark hidden pairing IDs seen | Mark only actually rendered/dismissed IDs; bounded/pruned set keyed by terminal status. | More than three pending, approval/removal, months of IDs. |
| Long chat/graph views retain excessive DOM/RAM | Virtualize long messages and graph side panels; cap retained graph data and dispose simulation/resources on hide/unmount. | Long thread, 2k-node graph, repeated navigation, heap snapshots. |
| Pending prompt/sessionStorage or pairing refs accumulate | TTL/version keys and cleanup on chat abandonment/terminal pairing state. | Create-never-open loop, reload, quota pressure. |

## Phase 6 — retention, cleanup, and accounting

Use one bounded maintenance coordinator with per-table policies, last-run metrics, dry-run
reporting, and `VACUUM` only as a separate user-visible maintenance action.

| Data | Policy |
|---|---|
| `app_jobs` | Keep active rows and recent failures; delete old succeeded/cancelled rows in batches while retaining aggregate diagnostics. |
| `chat_generations` | Retain active/retriable and a bounded diagnostic window; free old request IDs according to documented idempotency TTL. |
| retrieval snapshots/query cache | Automatic TTL/size budgets per vault; invalidate by source/index epoch; never wipe unrelated valid cache during content migration. |
| orphan vector chunks/sidecars | Reconcile incrementally after deletes and index publication; atomically delete only unreferenced epochs. |
| lock/extension/Bridge/CLI audit and sessions | Delete expired sessions promptly; retain security audit for configured duration/byte budget with export before purge. |
| quarantine originals | Reference-count encrypted artifacts and delete after source deletion/retention expiry; keep failed items long enough for recovery. |
| tombstones | Journaled startup cleanup for `.vault.deleted-*` after verifying ownership/path boundaries. |
| storage accounting | Report shared DB/vector bytes separately from vault-attributable bytes; never label global size as a single vault's usage. |

## Phase 7 — transactional integrity and setup

- Cluster rollback must be compare-and-swap: move a source back only if it still has the
  post-merge membership recorded by the operation. Deleted/moved sources become conflicts,
  not whole-operation failures. Update `reversible` when conflicts make full reversal impossible.
- Onboarding vault commit needs a durable staged journal (`prepared`, `created`, `path-set`,
  `setup-complete`) with idempotent resume/compensation and path identity checks.
- Setup-state writes need a process lock plus revision/compare-and-swap and atomic replace.
- Electron vault folder operations and recursive scans need canonical-path/symlink checks,
  root rejection, target-count/depth/byte limits, and cancellation.
- CLI/MCP response reads need streaming byte caps consistent with server limits.

## Verification matrix and release gates

1. **Per change:** unit plus direct database/API regression; static typing/lint; `git diff --check`.
2. **Per phase:** affected backend suites, Electron unit tests, desktop TypeScript build, extension tests.
3. **Rendered UI changes:** Playwright route flow with delayed/out-of-order responses, console check,
   desktop and narrow viewport. Browser plugin is preferred when available.
4. **Migration gate:** clean install, upgrade from every supported schema snapshot, rerun/idempotence,
   process kill at checkpoints, backup restore, no plaintext scan regressions.
5. **Scale gate:** synthetic 100k-source/1m-chunk vault, 5k watched files, long chat, 2k-node graph,
   huge LCOV/Git history. Record peak RSS, SQLite lock time, queue depth, p95 latency, and disk growth.
6. **Soak gate:** 72-hour mixed chat/import/watch/project/Bridge workload with backend restart,
   lock/unlock, model switch, sleep/wake, network loss, and disk-pressure injection.
7. **Packaging gate:** packaged Windows install, upgrade, reinstall/repair, uninstall, locked-file failure,
   interrupted install, helper integrity, Defender unavailable/recovery, and vault move/restart.

## Findings not scheduled as defects

The following reviewed claims did not reproduce in the current paths and should remain protected by
tests rather than receive speculative code changes: interpretation becoming ready before the
deterministic layer exists, Bridge idempotency crash wedge where reservation/completion are atomic,
unrecovered vault deletion tombstones where journal recovery already applies, MCP cancellation not
closing its HTTP request, and unbounded grounded prompts where the final token budget is already
enforced. Reopen only with a failing reproduction.
