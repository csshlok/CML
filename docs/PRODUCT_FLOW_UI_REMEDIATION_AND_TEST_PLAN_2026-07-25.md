# Vault Product Flow, UI Remediation, and Verification Plan

Date: 2026-07-25  
Status: implementation and verification record; Sections 1-17 preserve the audit and planned test contracts, while Sections 18 onward record the implemented behavior and evidence  
Scope: Electron startup and packaging, onboarding, vault lifecycle and security, local model and embedding setup, downloads, chat and background work, all authenticated desktop routes, shared shell behavior, CI, and packaged Windows verification

## 1. Purpose

This document consolidates:

1. The original 35-item UI/UX audit supplied during product review. The supplied list skipped number 31; this document preserves that numbering rather than inventing a missing finding.
2. The later 24-item behavior and efficiency audit.
3. Bugs found while testing onboarding, model downloads, memory search, packaged installation, vault startup, and lock behavior.
4. The deeper line-by-line lifecycle audit completed on 2026-07-25.
5. Recommended implementation mechanics for every confirmed issue.
6. Specific unit, integration, fault-injection, rendered UI, scale, CI, and packaged-app tests.

The central conclusion is that Vault's most important remaining problems are state-truth problems rather than visual styling problems. Several screens can currently report that a vault, model, download, security mode, generation, or cancelled job is ready even when the underlying system is not in that state. UI refinement must follow correction of those lifecycle contracts.

## 2. Evidence and Historical Baseline

> This section records the failing baseline that motivated the remediation. It is
> intentionally preserved for comparison and is superseded by the execution
> results in Sections 18 onward.

The audit used:

- Static review of Electron startup, renderer discovery, active-vault persistence, backend startup, and shutdown.
- Static review of onboarding, Settings, Chat, Sources, Home, Clusters, Map, Projects, Tasks, Timeline, Bridge, and shared shell code.
- Static review of model registry, model recommendation, GGUF download, embedding download, LLM runtime, unlock state, encryption helpers, background jobs, chat generation, and startup recovery.
- Targeted runtime probes using disposable data directories.
- Current local test execution.
- Prior rendered checks of onboarding at constrained desktop sizes.
- The previous UI audits in `docs/UI_UX_DEEP_AUDIT_2026-07-24.md` and `docs/UI_INTERACTION_AUDIT_2026-06-01.md`.

Current test baseline:

| Gate | Result | Meaning |
| --- | ---: | --- |
| Desktop typecheck and Electron shell tests | 41 passed | Current compile-time and existing shell contracts pass. |
| Backend quick tier | 367 passed | Existing quick backend tests pass. |
| `test_additional_qa_cases.py` | 104 passed, 2 failed | Integration CI currently fails two brittle source-text assertions. |
| Existing streamed-disconnect probe | Failed product invariant | Closing a stream after the first event leaves the generation `in_flight`. |
| Existing-security migration probe | Failed product invariant | Enabling security on an existing plaintext source leaves the plaintext column unchanged and creates zero encrypted rows. |

The two current integration-test failures are:

1. `test_bridge_route_wraps_long_operator_content_on_narrow_windows` expects an obsolete exact JSX substring even though the current `displayPath(...)` rendering retains the intended wrapping behavior.
2. `test_onboarding_route_uses_internal_scroll_shell_instead_of_hidden_root` expects the obsolete class `lg:max-h-[calc(100vh-4rem)]`; the implementation now uses a different internal layout.

These tests should be replaced with behavior and geometry assertions. They should not be made green by restoring obsolete source strings.

## 3. Current Sources of Truth

Vault currently splits product state across several stores:

| Concern | Current authority | Problem |
| --- | --- | --- |
| Active vault folder | Electron `active-vault.json` | It records a path, but no setup phase or migration state. |
| Displayed vault path/name | SQLite `vaults` row | It can disagree with the Electron path and actual database location. |
| Onboarding completion/profile | Browser `localStorage` | It is origin/port dependent and is not authoritative at startup. |
| Selected chat model | Model registry JSON | Selection does not start or verify a runtime. |
| Actual chat runtime | Environment-configured OpenAI-compatible endpoint | It is disconnected from the managed GGUF registry. |
| Model and embedding download progress | Backend process memory | It disappears on restart and cannot be reconciled reliably. |
| Unlock state | One backend-process global snapshot | It is not a durable or per-vault state machine. |
| Vault encryption keys | Backend-process memory | Convenience/PIN modes do not provide a complete restart flow. |
| Chat generation state | SQLite plus live generator state | Client disconnect is not finalized durably. |
| Background job state | SQLite | Running cancellation is not acknowledged by most handlers. |
| UI preferences | Browser `localStorage` | A packaged renderer port change can create a different origin. |

The remediation must reduce these to explicit, durable state machines with clear ownership.

## 4. Severity and Status Vocabulary

Severity:

- **P0:** can lose, expose, misroute, corrupt, or materially misrepresent user data or block the core product.
- **P1:** breaks a primary workflow, makes recovery unreliable, or becomes incorrect at realistic scale.
- **P2:** substantial usability, accessibility, consistency, or efficiency problem.
- **P3:** polish or optional productivity improvement.

Finding status:

- **Confirmed:** reproducible in current code or by a targeted probe.
- **Partial:** part of the original finding is fixed, but an underlying problem remains.
- **Outdated:** current code already addresses the reported behavior.
- **Misdiagnosed:** the proposed cause is not reproducible, although a related issue may remain.
- **Decision required:** behavior depends on a product/security policy that must be made explicit.

## 5. Target State Machines

### 5.1 Setup lifecycle

Persist this state outside browser storage:

```text
not_started
  -> profile_complete
  -> folder_prepared
  -> vault_created
  -> chat_model_pending | chat_model_ready | chat_model_skipped
  -> memory_pending | memory_ready | memory_skipped
  -> completion_verifying
  -> complete
```

Required invariants:

- `active-vault.json` is not sufficient evidence of completed onboarding.
- Startup resumes the first incomplete step.
- Every transition is idempotent.
- A failed transition leaves the previous committed phase intact.
- Finish is recorded only after a backend-identity and readiness verification.

### 5.2 Managed chat runtime lifecycle

```text
not_installed
  -> downloading
  -> verifying
  -> installed
  -> selected
  -> starting
  -> ready
  -> stopping | failed
```

Required invariants:

- `installed` never implies `ready`.
- `selected` never implies `ready`.
- `ready` requires a reachable supervised runtime and a bounded generation probe.
- Changing the selected model restarts the runtime transactionally.

### 5.3 Durable download lifecycle

```text
queued
  -> resolving
  -> downloading
  -> verifying
  -> installed

queued/resolving/downloading/verifying
  -> cancelling
  -> cancelled

any active state
  -> failed
```

Required invariants:

- Progress survives backend and desktop restarts.
- Cancelled means the worker has acknowledged cancellation.
- A partial file is either resumable and validated or safely discarded.
- Expected revision, filename, size, hash, ETag, and target path are durable.

### 5.4 Chat generation lifecycle

```text
created
  -> retrieving
  -> generating
  -> completed

retrieving/generating
  -> stopping
  -> stopped

retrieving/generating
  -> retriable | failed
```

Required invariants:

- Every stream exposes a generation ID in its first event.
- Every persistent stream reaches one terminal database state.
- Client EOF without a `done` event is never treated as success.
- A stopped partial answer is either persisted with explicit state or explicitly discarded by user choice.

### 5.5 Background job cancellation lifecycle

```text
queued -> running -> succeeded | failed
queued -> cancelled
running -> cancellation_requested -> cancelled
```

Required invariants:

- Running jobs do not become `cancelled` before the handler acknowledges cancellation.
- Long handlers check cancellation between bounded work units.
- A locked vault prevents new protected work and safely checkpoints or terminates active protected work.

### 5.6 Vault move lifecycle

```text
preflight
  -> writes_paused
  -> database_checkpointed
  -> copying_to_staging
  -> validating
  -> switching_active_pointer
  -> verifying_new_backend
  -> complete

any pre-complete state
  -> rolling_back
  -> rolled_back | repair_required
```

## 6. Critical Product and Lifecycle Findings

### PF-001: Onboarding completion is not durable

Severity: P0  
Status: Confirmed  
Current surfaces: `apps/desktop/src/routes/onboarding.tsx`, `apps/desktop/electron/main.cjs`, `apps/desktop/src/routes/index.tsx`

Current behavior:

- The vault path is prepared and committed during the folder step.
- Electron routes to `/home` whenever an active path exists.
- Models, Memory Search, and Finish are not represented in durable desktop state.
- `ctx.onboarded` is stored only in renderer `localStorage`.
- Closing after folder creation and reopening can bypass later setup.

Recommended implementation:

1. Add a versioned desktop setup-state file, written atomically.
2. Store phase, selected vault root, vault ID, selected model choice, embedding choice, skipped decisions, and transition timestamps.
3. Make `getInitialRendererPath()` use setup phase:
   - no state or `not_started`: `/onboarding`
   - incomplete phase: `/onboarding?resume=...`
   - `complete`: `/home`
4. Do not use `ctx.onboarded` for routing. It may remain temporarily for migration only.
5. On startup, reconcile setup state with backend identity and database contents.
6. If the state says complete but the backend points elsewhere, enter repair instead of Home.
7. Keep prepared folders recoverable without declaring them active.

Specific tests:

- `electron/setup-state.test.cjs::routes_new_install_to_onboarding`
  - Remove setup and active-vault files.
  - Assert initial route is `/onboarding`.
- `electron/setup-state.test.cjs::resumes_every_incomplete_phase`
  - Persist each non-terminal phase.
  - Assert the route contains the matching resume step.
- `electron/setup-state.test.cjs::active_path_without_complete_setup_does_not_open_home`
  - Persist a valid active path and `vault_created`.
  - Assert startup returns onboarding, not Home.
- `backend/tests/test_setup_lifecycle.py::test_transition_is_idempotent`
  - Apply the same transition twice.
  - Assert one durable state and no duplicate vault.
- `backend/tests/test_setup_lifecycle.py::test_invalid_transition_is_rejected`
  - Attempt `folder_prepared -> complete`.
  - Assert a conflict and unchanged durable state.
- Packaged Playwright: close and relaunch after every onboarding step; assert exact resume position and preserved form values.

### PF-002: Backend discovery does not validate vault identity

Severity: P0  
Status: Confirmed  
Current surfaces: `apps/desktop/src/lib/backend.ts`, `apps/desktop/electron/main.cjs`, `backend/app/api/routes/system.py`

Current behavior:

- Backend identity returns mode, data directory, database path, and instance ID.
- Electron and renderer discovery accept a backend primarily by service name, token, and API prefix.
- A stale authenticated backend on a candidate port can be accepted even when it belongs to another vault.
- The `backend-url-changed` callback changes a module variable but does not immediately publish a new verified health snapshot.

Recommended implementation:

1. Electron owns an expected backend descriptor containing instance ID, mode, normalized data directory, normalized database path, and launch generation.
2. Renderer requests the descriptor through preload rather than independently scanning arbitrary ports.
3. Any fallback discovery must compare every expected identity field.
4. A backend URL change publishes `checking`, verifies the descriptor, then publishes `online`.
5. Ongoing requests from a previous backend generation are aborted or ignored.

Specific tests:

- Start two authenticated fake backends using the same token but different data directories.
- Assert Electron selects only the exact expected descriptor.
- Return a valid service/API prefix with the wrong database path; assert degraded/offline, not online.
- Change backend URL while a slow request is in flight; assert its response cannot update route state.
- Packaged test: leave a stale development backend running and launch the installed app; assert the installed vault opens against its own backend.

### PF-003: Library location editing does not move the library

Severity: P0  
Status: Confirmed  
Current surface: `apps/desktop/src/routes/_app.settings.tsx`

Current behavior:

- Settings updates only the `vaults.path` column.
- Actual `.vault/cml.sqlite3`, Electron active path, backend process, blobs, staging data, and lock file stay at the old path.
- The UI reports “Library location saved.”

Recommended implementation:

1. Replace `updateVault({path})` from the UI with a desktop-level `moveVault` operation.
2. Preflight destination path, free space, permissions, filesystem type, existing `.vault`, and source/destination overlap.
3. Pause protected writes and wait for active jobs/generations to checkpoint or stop.
4. Checkpoint SQLite and create a verified backup.
5. Copy into a uniquely named staging directory.
6. Validate size, helper manifests where relevant, SQLite integrity, schema, and vault identity.
7. Shut down the old backend and wait for process exit and lock release.
8. Atomically switch the active pointer where possible.
9. Start and verify the new backend against the exact destination.
10. Update the vault record only after the new backend is verified.
11. Preserve the old `.vault` until the user confirms cleanup or a retention window expires.
12. Roll back the active pointer and restart the old backend on any failure.

Specific tests:

- Same-volume move success.
- Cross-volume move success.
- Destination already contains a vault.
- Destination runs out of space midway.
- Copy succeeds but SQLite integrity fails.
- New backend starts with wrong data directory.
- Old backend does not exit before timeout.
- App crashes during every move phase and resumes/rolls back on restart.
- Original source files outside `.vault` are never moved.
- UI does not report success until identity verification passes.

### PF-004: Vault deletion and active-pointer clearing are not transactional

Severity: P1  
Status: Confirmed

Current behavior:

- The database vault row is deleted first.
- Electron active-path clearing and backend restart happen afterward.
- If clearing/restart fails, the database can no longer contain the active vault row while Electron still points at its folder.
- Running work may still be mutating the database.

Recommended implementation:

1. Introduce a deletion transaction coordinated by Electron and backend.
2. Stop or checkpoint work.
3. Verify confirmation/passphrase.
4. Mark the vault `deleting`.
5. Clear/switch the active pointer and verify pre-vault backend readiness.
6. Delete logical records.
7. Move internal data to a recoverable trash/staging location if physical deletion is selected.
8. Record completion or repair state.

Specific tests:

- IPC clear failure after backend confirmation.
- Backend restart failure.
- Active job during deletion.
- Secured and unsecured vault deletion.
- Exact-name mismatch and wrong passphrase.
- Relaunch after crash in each deletion phase.

### PF-005: Installed/active chat model is disconnected from actual runtime

Severity: P0  
Status: Confirmed  
Current surfaces: `backend/app/core/model_registry.py`, `backend/app/core/llm_runtime.py`, onboarding, Settings

Current behavior:

- Activation writes `active_chat_model_id`.
- Chat uses `CML_LLM_PROVIDER`, `CML_LLM_BASE_URL`, and `CML_LLM_MODEL`.
- No packaged/supervised GGUF server consumes the managed model.
- Onboarding permits continuation while a managed download is still active.
- Download completion does not automatically make the runtime ready.
- Readiness verifies compatibility/registry state rather than a live generation.

Recommended implementation:

1. Package and verify a supported llama.cpp runtime.
2. Add a runtime supervisor with process ID, selected model, port, health, startup error, and logs.
3. `activate` becomes a transaction:
   - validate installed file and hash;
   - stop the previous runtime;
   - launch the selected model;
   - wait for `/models`;
   - run a minimal bounded generation;
   - mark ready only on success;
   - roll back to the previous model if startup fails.
4. Onboarding may continue only on `ready` or explicit skip.
5. Settings displays Installed, Selected, Starting, Ready, and Failed separately.
6. Imported formats are accepted only if the packaged runtime can execute them.

Specific tests:

- Downloaded file with no runtime binary is `installed`, never `ready`.
- Runtime process exits during startup; activation fails and previous model remains active.
- Runtime health passes but generation probe fails; state is failed.
- Changing models terminates the old process and verifies the new PID/model.
- App restart restores the selected model and starts it once.
- Chat request uses the selected managed model, not a stale environment model.
- Clean-machine packaged test downloads/uses a small fixture GGUF through a fake local artifact server.

### PF-006: Model downloads are not durable or resumable

Severity: P1  
Status: Confirmed

Current behavior:

- State and cancellation sets live in process memory.
- `.part` is opened with `wb`, restarting from zero.
- Backend restart loses progress.
- One model download globally blocks another, but that lock also disappears on restart.
- Resolver time can show no measurable progress.

Recommended implementation:

1. Store model downloads in a durable task table.
2. Persist target, expected size/hash, repo commit, filename, URL, ETag, bytes, speed sample, and timestamps.
3. Resume with Range/If-Range when the artifact server supports it.
4. If resume metadata does not match, quarantine and restart the partial.
5. Separate resolver progress from byte progress.
6. Reconcile durable tasks and `.part` files on startup.
7. Acknowledge cancellation only after the worker closes network/file handles.
8. Verify disk space with safety margin before and during download.

Specific tests:

- Restart at 25%, resume from the existing byte count, verify one final hash.
- Server ignores Range; downloader safely restarts.
- ETag changes; stale partial is quarantined.
- Hash mismatch never replaces the target.
- Cancel while blocked in network read; worker exits within a bounded timeout.
- Insufficient disk before start and during download.
- Two simultaneous requests return one active task rather than two writers.

### PF-007: Embedding download cancellation and runtime preflight are incomplete

Severity: P1  
Status: Confirmed

Current behavior:

- `sentence_transformers` is checked only inside the worker.
- A missing packaged dependency causes immediate failure after the user consents.
- Cancellation changes displayed state while `snapshot_download` may continue writing.
- Progress is inferred by rescanning the target directory.
- Task state disappears on restart.
- Memory Search is mandatory in onboarding, so a missing dependency/network can trap setup.

Recommended implementation:

1. Run dependency, model-access, disk, and destination checks before presenting an enabled Download action.
2. Run Hugging Face download in a cancellable subprocess or dedicated worker process.
3. Persist the download task and reconcile the local snapshot/cache.
4. Report file-level and aggregate progress without repeatedly traversing a large directory.
5. Keep the public MiniLM flow tokenless; request credentials only for an explicitly selected gated/private model.
6. Explain model source, license, approximate size, use, path, and account requirement before consent.
7. Add a degraded-mode skip with a confirmation explaining that semantic memory and source indexing features will be limited until configured.

Specific tests:

- Missing `sentence_transformers` disables download before consent and gives a repair action.
- Public model uses no Hugging Face token.
- Simulated 401/403 produces an account-required explanation.
- Cancellation terminates the worker and stops byte growth.
- Restart resumes/reconciles the snapshot.
- Skip records a durable `memory_skipped` phase and Settings shows a repair banner.
- Packaged runtime import test verifies all required Python modules.

### PF-008: Security initialization leaves existing plaintext and protects only part of the product

Severity: P0  
Status: Confirmed by direct probe  
Current surfaces: `backend/app/core/vault_crypto.py`, `backend/app/core/encrypted_storage.py`, unlock and Settings UI

Current behavior:

- Security initialization creates key metadata and loads a master key.
- It does not migrate pre-existing source content.
- Existing source text remains readable from SQLite.
- Chat messages are not routed through encrypted storage.
- Titles, paths, URLs, cluster/project metadata, and other fields remain plaintext.
- Convenience mode does not provide OS-backed automatic unlock.
- PIN metadata fields do not form a working PIN unlock flow.
- Global unlock state can be inconsistent with per-vault key material.

Recommended implementation:

1. Decide and document the exact at-rest protection boundary.
2. Do not display “security enabled” until migration completes and verifies.
3. Add a resumable encryption migration:
   - inventory protected plaintext;
   - write encrypted rows in bounded batches;
   - verify round-trip hashes;
   - clear plaintext columns;
   - checkpoint progress;
   - publish only after full verification.
4. Extend encryption to all user-content fields required by the product promise.
5. Make unlock state per vault and require the matching key for each request.
6. Implement convenience unlock using an OS-protected wrapped secret, or remove the mode.
7. Implement PIN wrapping and rate limiting fully, or remove PIN settings.
8. Remove `POST /vaults` from locked-safe routes.
9. Clear renderer-sensitive state synchronously on lock.

Specific tests:

- Populate every protected table before security initialization.
- Start migration and crash after each batch.
- Resume and assert no duplicate/lost rows.
- Query SQLite directly and assert known plaintext markers are absent.
- Decrypt every migrated record and compare exact content.
- Wrong vault key cannot authorize another secured vault.
- Locked `POST /vaults` returns 423.
- Locking on every primary route clears content, paths, citations, map labels, and previews within the same render turn.
- Convenience mode restart either unlocks through the OS store or is unavailable.
- Strict mode restart always requires the full secret.

### PF-009: New-vault and secured-vault lock semantics are conflated

Severity: P1  
Status: Partially fixed

The immediate bug where an unsecured new vault appeared locked was corrected by treating databases with no security metadata as ready. Remaining problems:

- Convenience mode still restarts locked.
- One process-global snapshot describes all secured vault rows.
- UI copy implies implemented convenience/PIN behavior.
- Locking does not guarantee cancellation/clearing of all active work and route state.

Recommended implementation:

- Keep unsecured vaults ready.
- Replace global state with `{vault_id -> state}`.
- Make convenience/strict behavior real and testable.
- Centralize renderer lock handling above the router outlet.

Tests:

- New unsecured vault opens ready.
- Secured strict vault restarts locked.
- Convenience behavior matches the documented policy.
- Lock one vault and ensure another vault state is not changed.

### PF-010: Stream disconnect/Stop can leave a generation permanently in flight

Severity: P0  
Status: Confirmed by direct probe

Current behavior:

- Generator cleanup catches `Exception`, not `GeneratorExit`.
- Disconnect after `meta` can leave `chat_generations.state = in_flight`.
- Client clears partial text on Abort.
- Client does not require a `done` event.
- Memory state can remain `indexing`.
- In-flight state can block unrelated jobs through synthesis conflict checks.

Recommended implementation:

1. Persist a generation before streaming and return its ID in `meta`.
2. Add explicit cancellation endpoint and cancellation token.
3. Use `try/except BaseException/finally` carefully so disconnect finalization always runs while process-level exceptions remain visible.
4. Store heartbeat and partial text at bounded intervals.
5. On Stop, transition to `stopping`, then `stopped`.
6. Persist/display the partial answer with a Stopped label and Retry action.
7. Client tracks whether `done` was received; EOF without `done` throws an interruption error.
8. Timeline reloads from durable state after interruption.
9. Release synthesis conflict immediately at a terminal state.

Specific tests:

- Disconnect immediately after `meta`.
- Disconnect after one token and after many tokens.
- User Stop through the cancel endpoint.
- Runtime timeout.
- Backend process termination during stream.
- Client receives normal EOF without `done`.
- Assert no scenario leaves `in_flight` after its cleanup timeout.
- Assert stopped partial text is preserved once, not duplicated.
- Assert queued background work resumes after generation termination.

### PF-011: Running job cancellation is reported before work actually stops

Severity: P0/P1 depending on job  
Status: Confirmed

Current behavior:

- `cancel_job()` sets a running job directly to `cancelled`.
- Many handlers never inspect job status.
- Work can continue mutating data after cancellation is displayed.
- Locking prevents new claims but does not interrupt every running handler.

Recommended implementation:

1. Add `cancellation_requested`.
2. Give every handler a cancellation token and bounded work units.
3. Check cancellation before and after each external call, transaction batch, and publication step.
4. Only the worker writes terminal `cancelled`.
5. For non-interruptible operations, show “Stopping after current step.”
6. Define rollback/checkpoint behavior per job type.

Specific tests:

- Parameterized cancellation contract covering every cancellable job type.
- Cancel while queued, before first write, mid-batch, before publication, and after publication.
- Assert terminal state matches actual side effects.
- Lock during each protected job.
- Verify non-protected diagnostics may continue only if policy permits.

### PF-012: All-or-nothing loaders make optional data block primary workflows

Severity: P1  
Status: Confirmed

Examples:

- Chat preloads clusters, sources, and chat list before loading the requested session.
- Settings groups many unrelated endpoints in one `Promise.all`.
- Bridge groups fourteen endpoints in one `Promise.all`.
- Cluster Detail loads sources, chats, peers, artifacts, projects, then performs an N+1 link lookup.
- Project Detail treats runs, links, and cluster lists as prerequisites for the project itself.

Recommended implementation:

- Load the route's primary record first.
- Give each optional panel an independent loading/error state.
- Preserve the last successful optional data during refresh.
- Add retry per failed panel.
- Use request generation IDs and abort signals.

Specific tests:

- Fail each optional endpoint individually and assert the primary workflow remains usable.
- Resolve an older request after a newer request; assert it is ignored.
- Navigate away during each load; assert no stale update.

### PF-013: Polling can overlap and create request storms

Severity: P1  
Status: Confirmed

Affected patterns include Settings, Tasks, Bridge, Home, and some project/runtime polling.

Recommended implementation:

- Use one shared visibility-aware scheduler.
- Schedule the next poll only after the previous poll finishes.
- Add exponential backoff and jitter when offline.
- Pause route-specific polling when the route is hidden.
- Deduplicate identical resource requests.

Tests:

- Make a poll take longer than its interval; assert maximum concurrency is one.
- Go offline for several minutes; assert bounded request count.
- Hide/show the document; assert immediate single refresh, not duplicate refreshes.

### PF-014: Packaged renderer browser storage is tied to a variable port

Severity: P1  
Status: Confirmed by architecture

Current behavior:

- Packaged renderer selects ports 5174-5190.
- Browser local storage belongs to the selected origin.
- A port change can create a different onboarding/preferences/profile store.

Recommended implementation:

- Move durable desktop state into an Electron-owned store or backend settings.
- Use a stable custom protocol/origin if browser storage remains necessary.
- Namespace preferences by vault ID.
- Migrate known keys from legacy origins when possible.

Tests:

- Launch renderer on two different ports and assert profile/setup/preferences remain identical.
- Switch vaults and assert vault-scoped preferences do not leak.

### PF-015: Readiness checks do not match onboarding or runtime truth

Severity: P1  
Status: Confirmed

Current behavior:

- First-run readiness treats active compatible model registry state as chat-ready.
- OCR can be included as a readiness requirement even though current onboarding does not configure it.
- Embedding summary can skip a full model probe.

Recommended implementation:

- Define separate readiness domains: vault, chat runtime, semantic memory, OCR, optional integrations.
- Overall app readiness should not require optional OCR.
- Each domain exposes `required`, `available`, `degraded`, `action`, and verified timestamp.
- Finish verifies only required or explicitly skipped domains.

Tests:

- App ready with OCR unavailable but OCR marked optional.
- Chat domain not ready when only a registry model exists.
- Embedding domain ready only after a local inference probe.

## 7. Original UI/UX Findings and Required Disposition

This section preserves the original numbering.

### UI-01: Eleven navigation items have equal weight

Status: Partial  
Fix:

- Keep Home, Chat, Search, Sources, Clusters, Map, and Projects as primary.
- Put Timeline, Tasks, Bridge, and Settings in a clearly separated secondary/system group.
- Validate order using usage telemetry or task analysis, not aesthetics alone.

Tests:

- Keyboard order matches visual order.
- Separator is exposed semantically.
- At 200% zoom, secondary navigation remains reachable without consuming most content width.

### UI-02: Sidebar cluster colors can disagree with cluster tint

Status: Fixed in current shell through normalized cluster color  
Regression test:

- Render clusters in reordered arrays and assert each sidebar dot uses its persisted cluster color, not index position.

### UI-03: Saved chats disappear outside Chat

Status: Outdated/changed by later design  
Current shell intentionally removed the duplicate global saved-chat block. Chat owns conversation navigation.

Required action:

- Do not restore a duplicate shell list without product evidence.
- Ensure the Chat route always exposes saved/recent navigation and an empty state.

Test:

- From every top-level route, open Chat and reach a saved conversation in at most two actions; assert the shell does not render a second conflicting conversation list.

### UI-04: Footer/status bar is overly dense

Status: Partial  
Fix:

- Keep service status, current vault name, and active work count.
- Remove redundant shortcut instructions and privacy slogans.
- Give every icon a label/tooltip.

Tests:

- Footer wraps/collapses at constrained widths.
- No unlabeled icon-only status.

### UI-05: Home quick actions lack feedback

Status: Fixed/partial  
Current quick actions are links and have interaction styling.

Regression tests:

- Hover, focus-visible, pressed, and keyboard activation.
- Exact route/search state for each action.

### UI-06: “Run analysis” navigates to generic Chat

Status: Confirmed product-copy mismatch unless renamed in current UI  
Fix:

- Rename to “Ask a question” if it opens an empty chat.
- If “Run analysis” remains, create a chat with explicit analysis mode and useful starter context.

Tests:

- Button label and destination intent match.
- Analysis action creates the expected mode, scope, and prompt.

### UI-07: Recent memories have poor subtitle fallbacks

Status: Partial  
Fix fallback:

1. generated summary;
2. first meaningful extracted-text excerpt;
3. source type and state;
4. never a raw local path unless the view explicitly requests it.

Tests:

- PDF metadata-only, URL, failed source, empty source, and long-path fixtures.

### UI-08: Suggested clusters are below the fold

Status: Decision required  
Fix:

- Prioritize actionable inbox/suggestion work above passive recent activity when suggestions exist.
- Do not force the section above the fold when empty.

Rendered tests:

- 1024x680, 1280x820, and 150% zoom with 0, 1, and 5 suggestions.

### UI-09: Chat status badges expose backend-like strings

Status: Partial  
Fix:

- One compact readiness summary with semantic status.
- Degraded status includes an exact Settings repair link.
- Technical provider/state strings move to Answer Details or Health.

Tests:

- ready, starting, missing, unreachable, busy, and failed fixtures.

### UI-10: Expanded/Complete analysis controls appear after every response

Status: Confirmed  
Fix:

- Move advanced analysis actions into a More/Analyze menu.
- Show only when indexed sources exist.
- Explain cost, scope, and difference.

Tests:

- Empty vault has no advanced analysis action.
- Keyboard and tooltip behavior.

### UI-11: Citation panel clears between answers

Status: Confirmed/needs state ownership  
Fix:

- Preserve the most recent completed answer's citations while the next answer streams.
- Associate citation state by message ID.
- Never replace existing evidence with a “next answer” placeholder.

Tests:

- Start a second response and assert first response citations remain until new citations arrive.
- Failed/stopped response preserves previous citations.

### UI-12: User and assistant messages lack clear differentiation

Status: Confirmed visual issue  
Fix:

- Use restrained alignment/background/accent differences.
- Preserve readable width and accessibility.

Visual regression:

- Mixed long user/assistant messages, code blocks, citations, high contrast, dark theme.

Interaction test:

- Given alternating user and assistant messages, each role has a programmatically available label and remains distinguishable in forced-colors mode.

### UI-13: Streaming and completed cards look identical

Status: Confirmed  
Fix:

- Add a non-distracting streaming accent and status.
- Respect reduced motion.

Tests:

- Streaming state is distinguishable without relying only on animation/color.

### UI-14: Chat loading is plain centered text

Status: Confirmed  
Fix:

- Use stable message skeletons.
- Distinguish loading from not-found and degraded.

Tests:

- Delay session loading and assert skeleton geometry reserves the final message width without layout shift.
- Return 404 and service-unavailable responses and assert neither is rendered as the loading skeleton.

### UI-15: Source table forces horizontal scrolling

Status: Confirmed at narrow desktop widths  
Fix:

- Hide/condense low-priority columns below width thresholds.
- Keep title/state/action usable.
- Provide inspector/detail for hidden metadata.

Rendered tests:

- 820px, 1024px, 125-200% zoom; no document-level horizontal overflow.

### UI-16: Sources search uses the wrong icon

Status: Confirmed minor issue  
Fix: use Search icon and accessible label.

Test:

- Render the source filter and assert it exposes a search role/name, uses the Search icon, and filters via keyboard input.

### UI-17: Sources view mode is not persisted

Status: Confirmed if the view toggle remains  
Fix:

- Persist vault-scoped preference outside unstable renderer-origin storage.

Tests:

- Navigate away/restart/switch vault.

### UI-18: Dead bulk-selection checkboxes

Status: Fixed by removal in prior UI pass  
Regression test:

- Interactive-control audit asserts no checkbox-shaped decorative controls.

### UI-19: Failed source inspector lacks recovery actions

Status: Partial  
Fix:

- Show failure reason, Retry indexing, Remove source, and diagnostics detail.
- Refresh state after reindex is queued/completed.

Tests:

- retry success, repeated failure, source deleted during retry, and locked/offline cases.

### UI-20: Cluster list columns waste space

Status: P2 layout issue  
Fix:

- Content-sized numeric columns and flexible name.
- Responsive hiding rather than fixed broad columns.

Rendered tests:

- At 820px, 1024px, and 150% zoom, long names truncate with an accessible full-name affordance, numeric columns remain aligned, and no page-level horizontal scrollbar appears.

### UI-21: Cluster suggestion dismissal lacks persistence/undo

Status: Fixed  
Regression tests:

- Dismiss, undo, reload, and per-vault isolation.

### UI-22: Cluster-detail Map is not cluster-focused

Status: Outdated  
The embedded cluster Map tab was removed. Do not restore it. The global authoritative Map should support deep-linked focus instead.

Regression test:

- Cluster detail exposes one “View on map” deep link; opening it focuses that cluster in the global Map and no duplicate embedded map route exists.

### UI-23: Empty Map has no action

Status: Fixed/partially implemented  
Regression:

- Zero-cluster overview shows explanatory copy and Create/Open Sources action.

Test:

- Activate the empty-state action by keyboard and assert it reaches the intended creation/import flow.

### UI-24: Map has no zoom-level indicator

Status: Fixed/partial  
Current map tracks a zoom value. Verify it reflects gesture zoom as well as button zoom.

Tests:

- wheel/pinch/button/fit operations update the same indicator.

### UI-25: Map lacks search/filter

Status: Fixed/partial  
Current KnowledgeMap has search and kind filtering.

Remaining tests:

- Large graph filter accuracy, keyboard navigation, zero matches, and focused-neighborhood behavior.

### UI-26: Settings section does not update URL

Status: Fixed  
Regression:

- Select each section, reload, use Back/Forward, and deep-link from an error.

Test:

- An invalid section parameter falls back predictably without replacing a valid browser-history entry.

### UI-27: Destructive Settings actions need a Danger Zone

Status: Partial  
Fix:

- Separate lock, delete, reset, and destructive maintenance by consequence.
- Lock is reversible but security-sensitive; deletion is destructive.
- Use explicit confirmation and focus restoration.

Tests:

- Visual/accessibility snapshot identifies the Danger Zone and destructive controls without relying on color alone.
- Cancel leaves state unchanged; confirm requires the documented phrase/step and restores focus or routes to a safe destination.

### UI-28: Welcome copy raises unnecessary account concerns

Status: Fixed by simplified welcome  
Regression:

- Welcome contains brand, one sentence at most, and one primary Start Setup action.

Rendered test:

- At the minimum supported window and 200% zoom, the welcome logo, heading, and action remain visible without internal scrolling or overlapping.

### UI-29: Eight onboarding steps are excessive

Status: Fixed/changed; current flow is six steps  
Remaining action:

- Let the durable lifecycle, not arbitrary page count, determine resumability.

Test:

- Interrupt setup after every durable transition, restart, and assert the user resumes at the first incomplete capability rather than a hard-coded page number.

### UI-30: Finish screen lacks a verified summary

Status: Partial  
Fix:

- Show vault name/location, chat runtime state or skip, memory state or skip, and any degraded capabilities.
- Summary values come from verified backend state, not selected frontend state.

Tests:

- Deliberately make the selected model fail activation; Finish reports the verified failure instead of “ready.”
- Every summary value matches the setup/backend descriptor and the final Continue action is blocked only for required incomplete capabilities.

### UI-31

No finding numbered 31 was supplied in the original audit.

### UI-32: Sidebar arrow-key navigation missing

Status: Fixed  
Regression:

- ArrowUp/ArrowDown cycle visible navigation items.
- Home/End behavior should be considered.
- Focus is visible and route activation remains Enter/Space.

Test:

- Hidden/disabled items are skipped, and arrow navigation does not unexpectedly change the route until activation.

### UI-33: Important errors appear only inline

Status: Partial  
Fix:

- Global toast for cross-page/action failures.
- Inline detail remains near the failed control.
- Avoid duplicate alerts for the same error.

Tests:

- import, runtime, vault lock, move, download, and reindex failures.
- screen-reader announcement happens once.

### UI-34: Page titles lack vault context

Status: Fixed in AppShell, but verify encoding and route coverage  
Fix:

- Use `Vault name — Page`.
- Ensure dialogs/startup pages are meaningful.

Tests:

- Visit every route with a Unicode vault name and assert a correctly encoded, context-rich document title.
- Startup, onboarding, recovery, and lock screens each expose distinct titles.

### UI-35: Focus does not move after navigation

Status: Fixed in AppShell  
Regression:

- Route navigation focuses main content.
- Dialog close restores triggering control.
- Inspector selection does not unexpectedly steal focus.

## 8. Earlier 24-Item Behavior Audit: Disposition and Tests

### B-01: Chat history loads without a limit

Status: Confirmed in Chat Detail; AppShell is already bounded  
Fix: server pagination, saved/recent filter, “Load more,” or virtualization.  
Test: create 500 sessions; initial request returns at most configured page size and renders bounded rows.

### B-02: Chat refetches broad sources/clusters/chats after each answer

Status: Confirmed  
Fix: update session from timeline result, fetch only citation source IDs, invalidate aggregate caches without immediate broad reload.  
Test: one response with three citations performs bounded targeted calls independent of vault size.

### B-03: Suggested prompt fills but does not submit

Status: Product decision  
Fix: either submit immediately or label “Use prompt” and visibly focus the composer.  
Test: accessible name accurately predicts behavior.

### B-04: Regenerate can find the wrong prior user message

Status: Original consecutive-send cause is misdiagnosed because sends are blocked while streaming.  
Remaining fix: associate regenerate with durable `reply_to_user_message_id`, not list scanning.  
Test: error, stopped, retry, imported timeline, and deleted-message fixtures regenerate the exact linked prompt.

### B-05: Attachment notice never clears

Status: Confirmed  
Fix: clear success notices after 5-6 seconds and immediately on the next attachment/send/navigation; keep actionable failures until dismissed/retried.  
Test: fake timers and navigation.

### B-06: Home unsorted excludes indexed unclustered sources

Status: Confirmed  
Fix: “Unsorted” means `cluster_id is null` regardless of indexed state; optional state filters remain separate.  
Test: waiting, processing, indexed, and failed unclustered fixtures all appear.

### B-07: Chat title blur concurrency

Status: Low-risk original claim; unchanged titles already short-circuit.  
Remaining fix: one in-flight mutation guard/version and visible failure.  
Test: two changed commits resolving out of order retain the newest title.

### B-08: Source pagination can become empty after mutation

Status: Confirmed  
Fix: after mutation, recompute total and clamp to the last valid page; do not always force page 1 unless product intent requires it.  
Test: delete/assign final item on last page.

### B-09: Home does not refresh on focus

Status: Confirmed  
Fix: shared resource invalidation plus focus refresh; show last-updated only when useful.  
Test: mutate while hidden, focus, assert one refresh.

### B-10: Chat sidebar includes unsaved sessions

Status: Confirmed for Chat's internal list  
Fix: define Saved versus Recent explicitly and paginate. Do not silently mix abandoned empty sessions.  
Test: saved, unsaved with messages, and empty sessions.

### B-11: Cluster Detail performs project-link N+1 requests

Status: Confirmed  
Fix: backend bulk endpoint `GET /cluster/{id}/project-links` or include links in a bounded cluster detail response.  
Test: request count remains constant with 100 projects.

### B-12: Source inspector auto-selects first source

Status: Product decision; not inherently a bug  
Confirmed related bug: previous pages/stats can remain visible while a new source loads.  
Fix: clear or mark inspector detail as refreshing on selection; persist explicit source ID in URL.  
Test: delayed old selection cannot overwrite new selection.

### B-13: Token-by-token smooth scrolling prevents reading earlier content

Status: Confirmed  
Fix: auto-follow only while the user is already near the bottom; pause when the user scrolls up; show Jump to latest.  
Test: stream 1,000 tokens, scroll up, assert viewport does not move.

### B-14: Stop discards partial answer

Status: Confirmed and expanded by PF-010  
Fix: durable stopped message with partial text and Retry.
Test: stop after a known streamed fragment; reload the chat and assert the exact fragment remains with `stopped` state and Retry targets the original user message.

### B-15: Analyze Again appears with no sources

Status: Confirmed  
Fix: gate by indexed source count and runtime readiness; explain disabled reason if retained.
Test: zero indexed sources, locked vault, and unavailable runtime do not expose an enabled Analyze Again action; ready fixtures do.

### B-16: Suggestion dismissal not persisted

Status: Outdated; fixed.
Regression test: dismiss, reload, undo, and switch vaults; dismissal persists only in the originating vault and undo restores exactly one suggestion.

### B-17: Deferred source search has no indication

Status: Outdated/partial; skeleton loading exists.  
Remaining improvement: preserve previous results with a subtle refreshing indicator rather than blanking on every keystroke.
Test: type a second query while the first result set is visible; previous results remain marked refreshing until the latest response replaces them, and stale responses cannot win.

### B-18: QuickAction may not be a real link

Status: Misdiagnosed; current actions are real links.  
Regression test: assert rendered anchor `href` and keyboard activation.

### B-19: No cluster rename from list

Status: P3 productivity enhancement  
Fix only if user research supports inline editing; otherwise keep one unambiguous detail workflow.
Acceptance test: the list offers one discoverable rename path; if inline rename is enabled, Escape cancels, Enter commits once, and a failed save restores the prior name.

### B-20: No empty state for chat list

Status: Confirmed  
Fix: “Saved chats appear here” plus New chat action; distinguish saved and recent.
Test: empty saved and recent datasets render explanatory copy and a keyboard-operable New chat action without an empty bordered panel.

### B-21: No save-chat/save-message keyboard shortcut

Status: P3  
Fix: Ctrl/Cmd+S saves chat only when browser-default interception is safe; expose in command palette. A single-letter shortcut must not fire while typing.
Test: shortcut saves once from the chat surface, appears in the command palette, and does not trigger inside inputs, editable content, or unsupported routes.

### B-22: Cluster merge consequence is ambiguous

Status: Confirmed  
Fix: name source and target, state that source cluster is removed, describe moved sources/chats, and mention reversible record/expiry.
Test: confirmation copy is populated with fixture names/counts; cancel changes nothing, confirm moves the documented entities, and Undo restores them within the stated window.

### B-23: Reindex feedback missing

Status: Partially fixed; toast exists but state does not refresh  
Fix: refresh the affected source/job state and link to Tasks.
Test: queue reindex, assert the source enters queued/running state without a page reload, and the toast’s Tasks link focuses the matching job.

### B-24: Map cannot navigate to cluster

Status: Confirmed  
Fix: selected authoritative cluster node exposes View cluster; preserve map focus in navigation history.
Test: focus a node, open its cluster, then navigate Back; the same map root, zoom, and selected node are restored.

## 9. Additional Route and Efficiency Findings from the Deep Pass

### D-01: Home metrics and activity are computed from bounded lists

Fix:

- Add aggregate endpoints for counts.
- Add a server-composed recent-activity feed sorted across entity types.
- Deep-link every source activity/memory row to its exact source.

Tests:

- 1,000 sources where the newest item is outside the first default page.
- Interleaved chat/source timestamps produce globally chronological activity.

### D-02: Search local filtering covers only the first 100 sources

Fix:

- Server-side search/filter/pagination for all query lengths.
- Semantic ranking returns hydrated result summaries.
- Reset/clamp pagination when query/filter changes.

Tests:

- Match exists at source 101+.
- Rapid query changes cannot show an old result set.

### D-03: Timeline uses bounded client collections

Fix:

- Add paginated user-content activity API.
- Exclude Tasks/Bridge operational events according to the information architecture.

Tests:

- Seed activity beyond the first source/chat pages and assert global chronological pagination returns it.
- Operational task/Bridge records do not appear unless an explicit operations filter is selected.

### D-04: Tasks performs a large N+1 poll every five seconds

Fix:

- Add one task/project-run summary endpoint.
- Poll only active IDs; paginate history.
- Use completion-based polling.

Tests:

- 100 projects still produce constant request count.
- One active run refreshes only that run.

### D-05: Bridge is one all-or-nothing 14-endpoint load

Fix:

- Split Overview, Clients, Reviews, History, and Advanced into URL-backed sections.
- Load section data independently.
- Preserve working controls when audit/history endpoints fail.
- Add catches and user-visible errors to every mutation; current `finally`-only handlers can reject silently.

Tests:

- Fail each endpoint independently.
- Every mutation produces success/failure feedback and restores enabled state.

### D-06: Map focus/inspect requests can resolve out of order

Fix:

- Abort previous neighborhood and inspect requests.
- Use request generation IDs.
- Keep selected/root IDs consistent with the current graph.

Test:

- Click A then B; resolve B then A; B remains selected and focused.

### D-07: Cluster Detail shows “not found” during initial loading

Fix:

- Separate `loading`, `loaded_not_found`, and `error`.
- Load cluster first; optional data afterward.

Tests:

- Delay a valid cluster response and assert a skeleton, never “not found.”
- Return 404 and 500 separately and assert distinct not-found and recovery states.

### D-08: Source list and inspector have stale-response risks

Fix:

- Abort/list request generations.
- Clear or mark pages/stats stale when selection changes.
- Clamp page after imports/deletes/assignment.
- Catch deletion failures.

Tests:

- Select A then B and resolve A last; B remains selected with B’s inspector data.
- Delete the final row on the final page and assert pagination clamps; failed deletion restores controls and reports the error.

### D-09: Source text/link import can report success when no vault exists

Current code sets a no-vault warning inside the branch, then continues to clear fields and set a success message.

Fix:

- Return immediately when no vault exists.

Tests:

- Invoke text/link handlers without a vault; no success message, fields stay intact, no dialog closes.

### D-10: Imports count existing duplicates as newly imported

Fix:

- Backend response distinguishes `created`, `already_present`, and `updated`.
- UI reports each category.

Test:

- Import a batch containing one new, one duplicate, and one updated source; backend counts and user message report `1/1/1`, not three created.

### D-11: Settings polling overwrites user drafts

Settings reloads backend paths/model configuration on a timer and can replace values while the user is editing.

Fix:

- Track dirty drafts.
- Poll status separately from editable configuration.
- Never overwrite dirty fields without conflict resolution.

Tests:

- Edit a path, let multiple polls finish, assert draft remains.

### D-12: One global Settings `saving` flag disables unrelated actions

Fix:

- Operation-specific pending IDs/states.
- Prevent duplicate operation, not all Settings work.

Test:

- While model activation is pending, an unrelated diagnostics export remains enabled; a second activation click is blocked and creates no duplicate request.

### D-13: Model recommendation refresh can overwrite user selection

The async recommendation response unconditionally sets `selectedModelId`.

Fix:

- Apply recommendation only before the user has made an explicit selection.
- Track `selectionSource: automatic | user`.

Test:

- User selects model B; delayed recommendation A resolves; B remains selected.

### D-14: Custom model import deletes destination before a successful copy

Current import removes an existing destination and then copies directly.

Fix:

- Copy into unique staging.
- Validate the staged model.
- Atomically swap destination and preserve prior version until success.

Tests:

- Copy failure and validation failure preserve existing imported model.

### D-15: Model discovery and execution formats disagree

Discovery finds Transformers checkpoint directories, while managed downloads are GGUF and the current chat runtime uses an external endpoint.

Fix:

- Define supported executable formats.
- Scan/import only formats with an end-to-end runtime path.
- Explain incompatible discoveries rather than presenting them as ready.

Tests:

- Scan fixtures containing supported GGUF, unsupported checkpoint directory, partial file, and corrupt model; only executable candidates can be selected as ready.
- A selected supported model completes runtime health inference before onboarding reports success.

### D-16: First-run profile/model localStorage values are written but not consumed

Fix:

- Persist profile and choices in a durable settings authority and consume them, or remove dead writes.

Test:

- Complete onboarding, restart with a changed renderer origin/port, and assert profile/model choices still load from the durable authority; no unused onboarding keys remain in localStorage.

### D-17: Active-vault config writes are not atomic and corrupt JSON is not repaired

Fix:

- Write temp, fsync where practical, rename.
- Validate schema/version.
- Quarantine corrupt config and enter repair.

Tests:

- Kill the writer between temporary write and rename; the previous committed config remains readable.
- Start with truncated/unknown-version JSON; it is quarantined and recovery opens without silently selecting a vault.

### D-18: Backend restart sends termination but does not wait for exit

Fix:

- Await child exit with timeout.
- Escalate termination only if required.
- Keep log streams open through exit.
- Do not launch a replacement until lock release is verified.

Tests:

- Delayed graceful shutdown and unresponsive child.

### D-19: Backend startup/restart rollback is incomplete

Preparing a new path sets `pendingActiveVaultPath` before restart. Failure can leave the pending path and backend URL in an inconsistent state.

Fix:

- Preserve previous committed descriptor.
- Clear pending state and restart previous backend on failure.

Test:

- Force the replacement backend to fail startup; pending state clears, the prior backend/descriptor becomes healthy again, and the renderer never binds to the failed URL.

### D-20: Source/chat action errors can be unhandled

Examples include delete chat, message save/useful toggles, project ask, and several Bridge mutations.

Fix:

- Shared mutation wrapper with operation-specific pending, toast/inline failure, and rollback.

Test:

- Parameterize delete chat, save/useful message, project ask, and Bridge mutations with rejected requests; each restores local state, announces one error, and produces no unhandled rejection.

### D-21: Chat optimistic attachment copy can contradict backend persistence

Attachments are ingested before generation completes. A later generation failure can cause the UI to say the attachment was not saved even when it was already stored.

Fix:

- Return/persist attachment ingestion result independently in `meta`.
- UI reports storage success separately from answer-generation success.

Tests:

- Attachment stored, runtime fails afterward; source remains and UI says stored, answer failed.

### D-22: Chat initial load swallows session errors as an empty/missing chat

Fix:

- Distinguish not-found, locked, offline, and optional preload failure.
- Never convert every exception to a blank session.

Test:

- Return 404, 423/locked, connection failure, and optional-sidebar failure; only 404 renders missing chat, while optional failure preserves the loaded conversation.

### D-23: Finished download can be left installed but not selected/started

Fix:

- If the user selected “download and use,” completion triggers verified activation.
- If the user navigated away or skipped, Settings shows Installed with explicit Use action.

Tests:

- Complete a “download and use” task and assert activation plus runtime health before ready.
- Complete after navigation/skip and assert Installed is durable, not silently active, with a working Use action.

### D-24: Download/notice UI lifetime is inconsistent

Fix:

- Success notices fade after 5-6 seconds or on route/step change.
- Active progress remains until terminal.
- Cancelled progress fades after acknowledgement.
- Failures remain until dismissed/retried.

## 10. Prior Packaging and Installed-App Incidents

These incidents were observed during the earlier packaging and onboarding test cycle. They need explicit release coverage even where the underlying cause overlaps a lifecycle finding above.

### PKG-01: Electron staging rename fails with `EPERM`

Observed behavior:

- `electron-builder` unpacked Electron into `release/win-unpacked.tmp` and then failed to rename it to `release/win-unpacked`.
- The packaging wrapper continued far enough to print a completion-style line and then failed artifact verification because `release/win-unpacked/CML.exe` did not exist.
- A running app, Explorer handle, antivirus scanner, stale builder process, or stale output directory can hold the stage directory open on Windows.

Required fix:

- Before packaging, detect running CML/Electron processes whose executable or working directory is inside the release tree and report their process IDs.
- Clean only the exact validated release staging directories.
- Retry the rename/build only for recognized transient sharing violations, with bounded exponential backoff.
- Preserve the first builder failure and exit immediately with a non-zero status. Never print `[DONE]` for a failed package step.
- Keep final artifact verification as an independent release gate.

Specific tests:

1. Hold a file handle inside `win-unpacked.tmp`; packaging must fail with a message that identifies the locked path and likely process, and must not print a success marker.
2. Simulate a transient first rename failure and successful retry; exactly one valid unpacked tree must remain.
3. Simulate a permanent lock; the wrapper must exit non-zero without deleting unrelated release files.
4. Run packaging twice consecutively after closing the app; both runs must produce the expected artifacts.

### PKG-02: Installed and unpacked executables were missing

Observed behavior:

- The unpacked output lacked `win-unpacked/CML.exe`.
- One installed build had no executable in the selected installation directory.
- The installer-created shortcut therefore could not resolve to a working executable.

Required fix:

- Treat all three outputs as mandatory: unpacked executable, NSIS installer, and installed executable.
- After silent installation into a disposable directory, resolve the Start Menu/Desktop shortcut target and verify that it equals the installed executable.
- Launch both unpacked and installed executables and wait for a healthy startup descriptor.

Specific tests:

1. Assert `release/win-unpacked/CML.exe` exists, is non-empty, and has the expected product metadata.
2. Install silently to a path containing spaces and assert the installed executable exists.
3. Resolve every CML shortcut and assert the target exists and launches.
4. Uninstall silently and assert the executable and owned shortcuts are removed without deleting user vault data.

### PKG-03: `package-logo.png` and application branding were not bundled consistently

Observed behavior:

- The onboarding welcome page rendered a broken image in the packaged app.
- Installer, application, shortcut, and uninstaller branding did not consistently use `package-logo.png`.

Required fix:

- Generate the platform-specific icon assets from the approved source image during a deterministic asset-preparation step.
- Bundle the renderer logo under an application-relative asset path that works in development and packaged `file`/custom-protocol contexts.
- Configure the executable, NSIS installer, shortcut, and uninstaller icons explicitly.
- Fail the package if any required brand asset is missing rather than falling back silently.

Specific tests:

1. Inspect the packaged archive/resources and assert the renderer logo is included at the path referenced by the built HTML/CSS.
2. Launch the packaged welcome page offline and assert the logo image has `naturalWidth > 0`.
3. Inspect executable, installer, shortcut, and uninstaller icon resources and compare them to approved visual snapshots.
4. Rename/remove the source logo before a test build; asset preparation must fail with a precise missing-file error.

### PKG-04: A fresh install reopened an old vault instead of onboarding

Observed behavior:

- Installing a new build reused the Electron user-data directory and its persisted `active-vault.json`.
- The app opened directly into a previously used vault, which looked like a broken fresh-install experience.

Product rule:

- An application update/reinstall should preserve a valid existing vault.
- A genuinely new user profile must enter onboarding.
- A user who wants to test first-run setup needs an explicit, safe “Reset app setup” action that clears application setup state without deleting vault contents.

Required fix:

- Implement PF-001’s durable setup state and validate the remembered vault before routing.
- Distinguish `fresh`, `existing-valid`, `existing-missing`, and `setup-in-progress`.
- For a missing remembered vault, show recovery choices: locate it, choose another vault, or start setup. Do not silently bind to `pre-vault`.

Specific tests:

1. Empty user-data directory routes to onboarding.
2. Reinstall with a valid completed setup reopens that vault.
3. Remembered path missing routes to recovery, not the main shell and not silent onboarding completion.
4. “Reset app setup” preserves the vault folder and database but returns the app to onboarding.

### PKG-05: New-vault startup displayed “Pre-vault backend is ready”

Observed behavior:

- After choosing a new vault, the diagnostic screen still reported the `pre-vault` data directory and database.
- The renderer had advanced while Electron/backend identity had not advanced to the selected vault.

Required fix:

- Implement PF-002’s exact backend identity handshake.
- Do not route past vault creation until the backend descriptor matches the selected vault ID, database path, and startup generation.
- Treat `pre-vault` readiness as valid only for onboarding endpoints.

Specific tests:

1. Start in pre-vault mode, create a vault, and assert the old process exits before the new descriptor is accepted.
2. Return a healthy descriptor for the wrong data directory; the renderer must remain in setup/recovery.
3. Assert no main-shell API request is sent to the pre-vault backend after the transition begins.
4. Packaged end-to-end test must display the selected vault path after transition.

### PKG-06: Managed model download failed because the integrity pin was missing

Observed behavior:

- The app refused to download `qwen3-4b-q4_k_m` because its trusted SHA-256 entry was missing.
- Refusal is the correct security behavior; shipping an incomplete or unreachable integrity manifest is not.

Required fix:

- Maintain one versioned model manifest containing model ID, immutable source revision, filename, byte size, and SHA-256.
- Bundle the manifest into packaged resources and validate it during CI and package startup.
- The UI must distinguish “catalog configuration is incomplete” from network/download failure.
- Never bypass the hash check as a recovery path.

Specific tests:

1. Every managed catalog entry has a valid 64-character SHA-256 and immutable source revision.
2. The packaged app can load the same manifest and resolve `qwen3-4b-q4_k_m`.
3. Missing entry blocks before network activity and presents a configuration error.
4. Hash mismatch deletes/quarantines the partial artifact and never marks the model installed.

### PKG-07: Packaged Python runtime lacked `SentenceTransformers`

Observed behavior:

- Memory Search reported that `SentenceTransformers` was not installed in the active Python runtime.
- The UI attempted to begin model setup before proving that the packaged embedding runtime was capable of loading it.

Required fix:

- Add embedding-runtime capability to the startup manifest and preflight.
- Package/import-test `sentence_transformers` and its transitive runtime dependencies in the exact shipped Python environment.
- Do not begin the model download until runtime capability, destination, consent, and free-space checks pass.

Specific tests:

1. Execute `import sentence_transformers` using the packaged interpreter on a clean machine.
2. Load the selected embedding model from a fixture/local cache with networking disabled.
3. Remove the dependency in a negative fixture; onboarding must show “required app component missing” before offering Download.
4. Verify cancellation leaves no model marked ready.

### PKG-08: Model and embedding download progress was not real-time or trustworthy

Observed behavior:

- The progress card could remain at zero while no visible file appeared at the selected location.
- Navigation and backend restarts could detach the UI from the in-memory task.
- A large notification covered the Continue button.

Required fix:

- Implement PF-006/PF-007 durable download records with bytes received, expected bytes, temporary path, speed, last heartbeat, and terminal state.
- Stream progress when connected and reconcile by polling the durable record after reconnect.
- Use a compact bottom-right progress surface containing short model name, progress bar, percentage, and cancel `X`; it must not cover primary navigation.
- Show model choices only after a writable location is chosen, space is measured, and recommendations account for hardware plus available disk.
- Show at most the top three recommendations, with plain-language size and capability explanations.

Specific tests:

1. Download from a throttled local HTTP fixture and assert byte/percentage updates before completion.
2. Assert the `.partial` file grows at the selected normalized location.
3. Reload/navigate away and back; progress resumes from durable state.
4. Restart the backend mid-download; the UI reconciles to resumed, failed, or safely resumable state.
5. Cancel; backend acknowledges, partial-file policy is applied, and the compact card fades.
6. Render at minimum supported window size and assert the progress surface does not overlap Continue/Back.

### PKG-09: Hugging Face account assumptions and consent were unclear

Observed behavior:

- Memory Search could begin fetching MiniLM without clearly naming the model, size, publisher/source, license implications, destination, or purpose.
- The product flow implied that all Hugging Face downloads require an account, although public model artifacts can normally be downloaded without authentication; gated/private repositories require user credentials and terms acceptance.

Required fix:

- Before any model network request, show model display name, repository/source, immutable revision, approximate size, destination, purpose, and whether authentication is required.
- Obtain explicit consent.
- Use anonymous downloads only for public, ungated artifacts.
- For gated/private artifacts, explain the requirement and provide a deliberate credential setup flow; never request a token for a public artifact.
- Store credentials only through the operating-system credential store, never in vault SQLite, logs, or browser storage.

Specific tests:

1. Public local-Hub fixture downloads without an auth header.
2. Gated fixture returns the consent/auth-required state and performs no retry loop.
3. No download request occurs before the user confirms.
4. Logs and persisted setup state contain no access token.
5. Skip opens an explanatory confirmation dialog; Cancel returns to the page and Confirm advances while recording `embedding_setup=skipped`.

### PKG-10: New vault opened in the locked state

Observed behavior:

- The vault created near the end of onboarding entered the main shell as locked even though the user had not enabled a lock mode requiring an immediate unlock.

Required fix:

- Implement PF-009’s explicit lock state machine.
- New unencrypted vaults start `unlocked`.
- A newly configured secure vault completes key setup and verifies access before leaving onboarding; the first main-shell transition remains usable.
- Restart behavior follows the selected security mode and is tested separately from same-process creation.

Specific tests:

1. Create an unencrypted vault and assert the first main-shell API call succeeds without unlock.
2. Configure PIN security, complete setup, and assert the current session is unlocked.
3. Restart and assert the configured restart-lock policy is applied.
4. Simulate key setup failure; onboarding must not mark setup complete or route to the main shell.

### PKG-11: User-facing paths displayed doubled or platform-inconsistent separators

Observed behavior:

- File and folder locations were sometimes rendered with doubled backslashes or raw backend escaping.
- The requested product convention is a single `/` separator in user-facing location text, including Windows locations.

Required fix:

- Preserve native paths internally and at filesystem boundaries.
- Route all displayed paths through `PathText`/`displayPath`, converting repeated `\` or `/` separators to one `/` without changing URI schemes or UNC semantics needed for actual operations.
- Never feed the display-normalized value back into filesystem APIs.

Specific tests:

1. `C:\Users\Name\Vault` displays as `C:/Users/Name/Vault`.
2. Escaped input with doubled separators displays only one separator.
3. `https://host/path` remains a valid URL and is not reduced to `https:/host/path`.
4. Native-path round-trip tests prove display formatting does not mutate the stored filesystem path.

## 11. Shared Implementation Components and Services

Build these as behavior-bearing primitives, not visual wrappers:

1. `DesktopSetupStateStore`
2. `BackendDescriptorCoordinator`
3. `VaultMigrationCoordinator`
4. `ManagedModelRuntimeSupervisor`
5. `DurableDownloadService`
6. `GenerationCancellationService`
7. `JobCancellationToken`
8. `RequestGenerationGuard`
9. `VisiblePollingCoordinator`
10. `AsyncActionButton`
11. `OperationNotice`
12. `DegradedState`
13. `SkeletonRegion`
14. `EntityInspector`
15. `EvidenceDisclosure`
16. `PathText`
17. `DangerZone`
18. `AppStatusAnnouncer`

Each shared UI component must replace at least two route-specific implementations in the same delivery phase.

## 12. Detailed Test Architecture

### 12.1 Unit tests

Unit tests cover pure state transitions and normalization:

- setup transition reducer and serialization;
- backend descriptor comparison and path normalization;
- download progress/resume metadata;
- model runtime state derivation;
- stream terminal-event tracking;
- pagination clamping;
- activity sorting;
- status/copy mapping;
- path display;
- operation-notice lifetime;
- cluster color mapping;
- suggestion persistence;
- merge consequence copy.

Unit tests must assert behavior and returned state, not exact source-code strings or Tailwind class substrings.

### 12.2 Backend integration tests

Add focused modules:

```text
backend/tests/test_setup_lifecycle.py
backend/tests/test_backend_identity_contract.py
backend/tests/test_vault_move_lifecycle.py
backend/tests/test_security_migration_end_to_end.py
backend/tests/test_managed_runtime_supervision.py
backend/tests/test_durable_model_downloads.py
backend/tests/test_durable_embedding_downloads.py
backend/tests/test_stream_disconnect_and_cancel.py
backend/tests/test_job_cancellation_contract.py
backend/tests/test_route_partial_failure_contracts.py
```

Use temporary data directories, fake artifact/runtime HTTP servers, deterministic files, and injected failure points. Tests must not depend on public network access.

### 12.3 Electron shell tests

Add:

```text
apps/desktop/electron/setup-state.test.cjs
apps/desktop/electron/backend-descriptor.test.cjs
apps/desktop/electron/backend-restart.test.cjs
apps/desktop/electron/vault-move.test.cjs
apps/desktop/electron/stable-renderer-state.test.cjs
apps/desktop/electron/runtime-supervisor.test.cjs
```

Critical assertions:

- atomic config writes;
- exact-path backend identity;
- graceful process exit before restart;
- rollback to previous backend;
- setup resume routing;
- stable desktop preferences across renderer ports;
- runtime process cleanup on app quit.

### 12.4 Frontend component/integration tests

Use React Testing Library or the project's selected component test harness:

- primary content remains when an optional panel fails;
- stale requests are ignored;
- notices clear according to policy;
- dirty drafts survive polling;
- operation-specific pending states;
- stopped chat message rendering;
- citation persistence;
- source pagination clamping;
- cluster merge copy;
- lock boundary clears sensitive route state.

### 12.5 Playwright rendered tests

Run against both development renderer and packaged Electron.

Required viewport matrix:

- 1024x680
- 1280x820
- 1440x900
- effective 200% zoom/narrow CSS viewport

Required state matrix:

- empty vault;
- populated vault;
- mixed source states;
- backend offline;
- wrong backend identity;
- vault locked;
- chat runtime unavailable;
- embedding runtime unavailable;
- active/cancelled/failed downloads;
- active/cancelling/failed jobs;
- long names, paths, and errors;
- reduced motion;
- keyboard-only navigation.

### 12.6 Packaged clean-machine tests

The installer test must verify:

1. Application and uninstaller logos are present.
2. Start Menu/Desktop shortcuts point to the installed executable.
3. Installed folder contains the expected executable.
4. First launch opens Welcome, not an old vault.
5. Onboarding can be closed/reopened at every step.
6. Packaged Python imports SentenceTransformers and Hugging Face dependencies.
7. Managed runtime binary exists and passes integrity checks.
8. Public embedding download starts without an account.
9. Model download persists through desktop restart.
10. Installed model reaches actual runtime-ready state.
11. New vault is ready unless security was explicitly enabled.
12. Uninstaller starts and uses the packaged icon.

### 12.7 Scale tests

Fixtures:

- 10,000 sources;
- 1,000 chats;
- 1,000 clusters/map nodes;
- 100 projects with run history;
- 10,000 background jobs;
- long paths and Unicode names.

Budgets:

- Initial route requests are bounded and paginated.
- Request count for Cluster Detail and Tasks remains constant relative to project count.
- No renderer O(n²) graph construction.
- No broad source refetch after one chat answer.
- No overlapping polling.

## 13. Fault-Injection Matrix

Every multi-step lifecycle must expose deterministic failpoints in tests.

| Lifecycle | Inject failure after | Required result |
| --- | --- | --- |
| Setup | folder creation | Resume folder step; no completed active vault. |
| Setup | vault DB creation | Resume safely without duplicate vault. |
| Setup | model download | Resume Models with durable task. |
| Setup | memory download | Resume Memory with durable task. |
| Setup | finish verification | Stay incomplete and explain repair. |
| Backend restart | terminate signal | Wait or escalate; never run two writers. |
| Backend restart | replacement spawn | Restore previous descriptor/backend. |
| Vault move | preflight | No mutation. |
| Vault move | partial copy | Staging retained/quarantined; old vault active. |
| Vault move | validation | Old vault active. |
| Vault move | pointer switch | Roll back or enter explicit repair. |
| Security migration | any batch | Resume from checkpoint; plaintext not prematurely cleared. |
| Model download | network interruption | Durable resumable partial. |
| Model download | hash verification | Target not published. |
| Embedding download | worker termination | Reconcile on restart. |
| Chat | client disconnect | Terminal stopped/retriable state. |
| Chat | runtime timeout | User prompt durable; no in-flight leak. |
| Job | cancellation request | Stop at next bounded checkpoint. |
| Lock | active stream/job | Sensitive UI clears and backend work terminates/checkpoints. |

## 14. CI Changes

### 14.1 Replace brittle source assertions

Remove tests that assert exact Tailwind classes or JSX substrings when the requirement is geometry or behavior.

Replace with:

- rendered no-overflow checks;
- accessible control queries;
- click/keyboard behavior;
- exact navigation/API side effect;
- screenshots only where geometry matters.

### 14.2 Required CI jobs

1. Dependency audit.
2. Desktop typecheck and shell unit tests.
3. Backend quick.
4. Backend integration.
5. Backend system/security.
6. Backend benchmark.
7. Frontend component tests.
8. Playwright renderer flows.
9. Windows packaged smoke test.
10. Optional scheduled scale and interruption suite.

### 14.3 New release-blocking invariants

CI must fail if:

- an onboarding phase can route Home before complete;
- backend identity does not match the expected vault;
- any persistent chat disconnect leaves `in_flight`;
- any cancelled running job continues past its acknowledged terminal state;
- security migration leaves protected plaintext markers;
- model registry says ready without a live generation probe;
- active download state is lost after simulated restart;
- a primary route fails when only an optional panel endpoint fails;
- packaged runtime dependencies or executable assets are missing.

## 15. Delivery Phases

### Phase 0: Contract freeze and test harness

- Add durable-state schemas and transition tests.
- Add fake runtime/artifact servers and failure injection.
- Replace the two current brittle QA assertions.
- Add baseline tests that currently fail for setup interruption, stream disconnect, security migration, job cancellation, and wrong-backend identity.

Exit gate:

- Every P0 bug has a failing automated reproduction before its implementation lands.

### Phase 1: Setup and backend identity

- Durable setup state.
- Resume routing.
- Atomic active-vault config.
- Exact backend descriptor.
- Restart wait/rollback.

Exit gate:

- Packaged app resumes every setup step and never attaches to a wrong vault backend.

### Phase 2: Security, lock, move, and deletion

- Per-vault unlock.
- Security migration and truthful UI.
- Convenience/PIN product decision and implementation/removal.
- Synchronous renderer lock boundary.
- Transactional move/delete.

Exit gate:

- Protected plaintext test passes and every move/delete fault rolls back safely.

### Phase 3: Managed runtime and durable downloads

- Supervised GGUF runtime.
- Verified activation.
- Durable model and embedding downloads.
- Real cancellation/resume.
- Public/gated Hugging Face policy.

Exit gate:

- Clean packaged machine can download, restart, resume, activate, and generate.

### Phase 4: Chat and job interruption

- Generation IDs and cancel endpoint.
- Partial stopped responses.
- EOF validation.
- Cooperative job cancellation.
- Lock interaction.

Exit gate:

- No in-flight generation leak and no post-cancellation mutation.

### Phase 5: Request orchestration and scale

- Independent loading boundaries.
- Request-generation guards.
- Shared polling coordinator.
- Server pagination/aggregates.
- Bulk project/task endpoints.

Exit gate:

- Scale fixtures stay accurate and bounded.

### Phase 6: Route UI remediation

- Navigation/footer.
- Home.
- Chat presentation/evidence.
- Sources.
- Clusters.
- Map.
- Settings.
- Bridge.
- Onboarding copy/layout/final summary.
- Accessibility/status/focus.

Exit gate:

- All original UI findings are fixed, intentionally rejected, or explicitly deferred with product rationale.

### Phase 7: Packaged release proof

- Installer/executable/shortcut/logo checks.
- Clean-machine onboarding and runtime.
- Upgrade and old-vault behavior.
- Uninstall.
- Full CI and scheduled interruption suite.

## 16. Definition of Done

The program is complete only when:

- Startup cannot confuse a prepared vault with completed onboarding.
- Renderer and Electron agree on one exact backend/vault identity.
- Library move and deletion have verified rollback.
- Installed/selected/ready model states are truthful.
- Downloads survive restart and cancel only after worker acknowledgement.
- Security either protects the documented data set after verified migration or the UI truthfully describes its narrower boundary.
- New unsecured vaults do not open locked.
- Convenience/strict/PIN behavior matches implementation.
- Every persistent generation reaches a terminal state.
- Running jobs do not mutate after terminal cancellation.
- Optional panel failures do not block primary route tasks.
- Polling is bounded, visibility-aware, and non-overlapping.
- Counts/search/activity remain correct beyond default page limits.
- All original UI findings have a recorded disposition and regression test where applicable.
- Packaged Windows behavior is verified, not inferred from Vite development mode.

## 17. Traceability Checklist

Implementation pull requests should reference:

- one or more `PF-*`, `UI-*`, `B-*`, `D-*`, or `PKG-*` IDs;
- the state transition being changed;
- the exact new tests;
- rollback behavior;
- packaged-app impact;
- user-facing copy impact;
- whether data migration is required.

A finding is closed only when its implementation, tests, failure behavior, and packaged verification are all complete.

## 18. Implementation Record

This section distinguishes code that now exists from recommendations that remain
deliberate product choices. The detailed cause, proposed behavior, and test case
for every identifier remain in Sections 6-10; this section records the resulting
system.

### 18.1 Durable setup, first launch, and product tour

Implemented behavior:

- Electron owns an atomic, versioned setup-state document instead of relying on
  renderer `localStorage` to decide whether onboarding is complete.
- Setup records the active phase, selected vault, profile, model decisions,
  embedding consent, completion time, and first-use-tour state.
- An interrupted setup resumes its last durable phase. A prepared database is
  not treated as proof that onboarding finished.
- A clean renderer profile always enters onboarding. An existing profile enters
  the last valid setup state only after its backend identity is verified.
- The renderer can read and update setup and tour state through a narrow preload
  bridge. It does not receive unrestricted filesystem access.
- The post-onboarding vault is created unlocked unless the user explicitly
  enabled a security mode that requires locking.
- Onboarding status notices are tied to the active step and have a bounded
  lifetime. Navigating away removes them immediately.
- The first-use product tour is durable, dismissible, keyboard accessible, and
  shown once after successful setup. It identifies the primary navigation,
  source import, Chat, and Settings/Health recovery path without blocking normal
  use.

Primary automated evidence:

- `apps/desktop/electron/setup-state.test.cjs` covers clean state, atomic writes,
  invalid-state recovery, interrupted-step resume, completion, and tour
  acknowledgement.
- `apps/desktop/electron/main.behavior.test.cjs` covers startup routing,
  renderer/backend identity, setup IPC, lock boundaries, and first-use state.
- Rendered Playwright checks cover the welcome page, all onboarding panel
  geometry, constrained window sizes, forward/back transitions, and tour
  completion.
- Packaged launch smoke uses an explicit isolated Electron `userData` directory
  and requires the first route in the runtime log to be `/onboarding`.

Closed or materially addressed findings:

- `PF-001`, `PF-002`, `PF-009`, `PF-014`, `PF-015`
- `D-16`, `D-17`, `D-18`, `D-19`
- `PKG-04`, `PKG-05`, `PKG-10`
- `UI-28`, `UI-29`, `UI-30`, `UI-34`, `UI-35`

### 18.2 Backend identity and transactional vault lifecycle

Implemented behavior:

- Every backend process publishes a descriptor containing the exact vault
  identity, normalized data root, database path, process identity, API
  compatibility version, and readiness phase.
- Electron accepts an existing backend only when the descriptor matches the
  expected vault. Port reachability alone is never considered identity proof.
- Restart waits for the old process to exit, starts the candidate process,
  verifies its descriptor and health, and updates the active pointer only after
  successful verification.
- Failure preserves or restores the previous valid active configuration.
- Vault relocation is a staged copy/verify/switch transaction. It does not
  relabel the SQLite row while leaving files behind.
- Vault deletion validates the exact target, refuses unsafe/broad paths, closes
  active resources, removes the active pointer transactionally, and requires
  explicit authorization.
- Interrupted or failed migrations place startup in a visible safe degraded
  mode with a recovery issue instead of reporting normal readiness.

Primary automated evidence:

- Backend vault route tests cover move success, destination collision, copy
  failure, verification failure, rollback, and active-vault deletion.
- `backend/tests/test_vault_deletion_authorization.py` covers authorization,
  exact target validation, and refusal of unsafe deletion targets.
- Electron behavior tests cover wrong-vault backend rejection and
  restart/rollback.
- `smoke-packaged-migration-drill.ps1` injects an interrupted migration and
  requires degraded mode plus a surfaced recovery issue.

Closed or materially addressed findings:

- `PF-002`, `PF-003`, `PF-004`
- `D-17`, `D-18`, `D-19`

### 18.3 Vault security, lock state, and encrypted records

Implemented behavior:

- Unlock state is scoped to a vault identity; a stale global lock snapshot
  cannot lock a newly created unrelated vault.
- Security activation is a migration, not a UI flag. Existing protected source
  and chat fields are encrypted and verified before the product reports the
  stronger security state.
- A failed migration leaves a recoverable state and never claims completion.
- Renderer lock is a synchronous boundary: sensitive state is cleared before
  navigation and subsequent requests require a valid unlocked vault.
- Citation records referring to deleted sources are retained as encrypted
  tombstones with `state: source_deleted`; they neither expose stale protected
  content nor silently imply that the source still exists.

Primary automated evidence:

- `backend/tests/test_unlock_phase2.py` and
  `backend/tests/test_system_vault_lock_and_embeddings.py` cover per-vault lock
  semantics, new-vault unlocked behavior, unlock transitions, and security
  migration.
- Source/chat deletion tests verify citation tombstoning for both ordinary and
  chat-owned sources.
- Migration fault tests search protected plaintext markers after successful
  migration and require none to remain in the protected columns.

Closed or materially addressed findings:

- `PF-008`, `PF-009`
- `PKG-10`

### 18.4 Managed chat models and truthful readiness

Implemented behavior:

- Managed chat models accept executable GGUF artifacts only. Discovery results
  and runtime execution therefore use the same format contract.
- Every downloadable managed artifact has a trusted SHA-256 pin. Missing or
  mismatched integrity data is a hard failure before activation.
- Download, installation, selection, runtime launch, health, and generation are
  separate states.
- Selecting a model starts the supervised local runtime and readiness requires
  a live generation-compatible probe; a registry flag alone cannot report
  ready.
- Runtime process ownership, ports, logs, and shutdown are managed by a
  supervisor rather than an unrelated environment-configured endpoint.
- Recommendation considers memory, CPU/GPU information, and free space at the
  user-selected download location. Choices are hidden until a valid location
  exists and the UI presents only the strongest suitable short list.
- Public Hugging Face artifacts download without an account. Gated/private
  artifacts clearly request authentication and never imply that every download
  needs an account.

Primary automated evidence:

- `backend/tests/test_managed_model_runtime.py` covers integrity pins, corrupt
  artifacts, supervised launch, failed launch, truthful readiness, generation
  probe, and shutdown.
- `backend/tests/test_model_recommender.py` covers GGUF-only choices and
  disk-aware ranking.
- `backend/tests/test_runtime_contracts.py` covers status semantics and API
  compatibility.
- The packaged runtime smoke imports and starts the bundled runtime from
  `win-unpacked`, not from the developer environment.

Closed or materially addressed findings:

- `PF-005`, `PF-015`
- `D-13`, `D-14`, `D-15`, `D-23`
- `PKG-06`, `PKG-08`, `PKG-09`

### 18.5 Durable model and embedding downloads

Implemented behavior:

- Download records are persisted with artifact identity, destination, expected
  size/hash, bytes received, state, timestamps, temporary path, and failure
  reason.
- Partial artifacts use resumable temporary files. Restart reconciles the
  persisted record with the file and resumes only when the server and artifact
  identity permit it.
- Progress comes from bytes written by the worker and is rate-limited for the
  UI. It is not a simulated timer.
- Cancel changes a download to cancellation-requested first. The worker closes
  the response/file and acknowledges the terminal cancelled state.
- The compact notification shows a short model name, progress bar, percentage,
  and an `X`; it never covers onboarding navigation and disappears after
  acknowledged cancellation.
- Embedding setup explains MiniLM's purpose, source, size, storage location, and
  local processing before consent. The user may skip after confirming the
  effect and can configure it later.
- Embedding download runs in a dedicated worker. Status checks do not import
  Torch or instantiate SentenceTransformers merely to render a page.
- The embedding path resolver supports a direct model directory, a named child
  directory such as `all-MiniLM-L6-v2`, and Hugging Face snapshot layouts.

Primary automated evidence:

- `backend/tests/test_durable_download_state.py` covers persistence, restart
  reconciliation, byte progress, range resume, no-range restart, cancellation,
  hash failure, and destination validation.
- Embedding worker tests cover consent, missing runtime, progress, cancellation,
  direct/child/snapshot paths, and activation.
- Packaged Python validation imports `sentence_transformers` and
  `huggingface_hub` from the bundled interpreter.

Closed or materially addressed findings:

- `PF-006`, `PF-007`
- `D-23`, `D-24`
- `PKG-07`, `PKG-08`, `PKG-09`

### 18.6 Chat terminal states and background cancellation

Implemented behavior:

- Each generation has a durable identifier and reaches one terminal state:
  completed, stopped, failed, or disconnected.
- Stop and client disconnect retain useful partial text and finalize the
  generation instead of leaving `in_flight`.
- Regeneration targets an explicit message/generation relationship rather than
  searching for a loosely adjacent user message.
- Background jobs now distinguish a cancellation request from worker
  acknowledgement. A running job remains running with
  `cancellation_requested=true` until its handler stops safely.
- Queued/blocked jobs may cancel immediately because no handler owns side
  effects. Recovery acknowledges a pending cancellation instead of resuming it.
- Encrypted citation tombstones keep historical answers coherent after source
  deletion.

Primary automated evidence:

- Chat route and memory tests cover normal EOF, stream failure, explicit stop,
  client disconnect, partial persistence, regeneration identity, and citation
  deletion.
- `backend/tests/test_background_jobs.py` covers queued cancellation, running
  request/acknowledgement, recovery, and the prohibition on mutation after the
  terminal cancelled state.

Closed or materially addressed findings:

- `PF-010`, `PF-011`
- `B-04`, `B-14`
- `D-21`, `D-22`

### 18.7 Request orchestration, bounded polling, and scale

Implemented behavior:

- Primary route content and optional panels have independent loading/error
  boundaries. Optional Bridge, citation, or diagnostic failures do not erase
  usable primary data.
- Request-generation guards prevent an older response from replacing a newer
  source selection, Map focus, model recommendation, Settings draft, or route
  query.
- Visible polling is shared, visibility-aware, non-overlapping, and abortable.
- Home metrics, activity, Search, Timeline, Tasks, projects, and cluster
  relationships use server pagination/aggregates instead of assuming the first
  default page represents the vault.
- Bulk endpoints replace the largest project/task N+1 request patterns.
- Source pagination clamps after mutations so the user cannot be left on an
  empty out-of-range page.

Primary automated evidence:

- Route behavior tests cover stale response ordering, optional endpoint
  failure, pagination clamp, focus refresh, and non-overlapping polling.
- `backend/tests/test_odin_scale.py` validates 50,000-file discovery under the
  explicit scale gate and validates metadata queries with 10,000 sources,
  1,000 chats, 1,000 clusters, and 10,000 jobs.
- Latest measured scale run used 68.3 MiB peak memory; metadata query work
  completed in 0.092 seconds. The 50,000-file discovery fixture completed in
  92.914 seconds on this Windows test machine.

Closed or materially addressed findings:

- `PF-012`, `PF-013`
- `B-01`, `B-02`, `B-06`, `B-07`, `B-08`, `B-09`, `B-11`
- `D-01` through `D-13`, `D-20`

### 18.8 UI remediation and simplified onboarding

Implemented behavior:

- Onboarding follows the supplied reference's location and scale: a narrow
  left progress rail, a centered bounded work card, a stable card header/body/
  footer, generous whitespace, and navigation that stays reachable.
- Vault branding and packaged logo are retained; only the reference geometry
  and information hierarchy were adopted.
- Welcome is intentionally minimal. Location precedes model choice. Model and
  memory-search pages use plain language, progressive disclosure, explicit
  consent, skip confirmation, and compact progress.
- User-facing paths are normalized to forward slashes for display while native
  paths remain unchanged internally.
- Navigation is grouped by workflow importance, cluster tint is stable, the
  footer is reduced, route titles include vault context, and focus moves to the
  main content after navigation.
- Home, Chat, Sources, Clusters, Map, Settings, Bridge, Projects, Tasks, and
  Timeline received route-specific empty, loading, failure, responsive, stale-
  request, and interaction treatments described in Sections 7-9.
- The Map has an empty action, zoom value/reset, search/filter, cluster focus,
  and keyboard-accessible navigation.
- Sources use the correct search affordance, persisted view mode, responsive
  columns, no fake selection controls, and failed-source retry/removal.
- Chat differentiates roles and streaming state, retains recent citations, uses
  skeleton loading, and reduces advanced-analysis controls.
- Settings sections deep-link through the URL and destructive actions are
  isolated in a Danger Zone.
- Important operation failures use compact toasts while persistent/recoverable
  details remain inline.

Specific UI regression checks:

- Geometry checks assert sidebar width, work-card maximum width and height,
  footer position, vertical centering, and no clipped controls at constrained
  desktop sizes.
- Keyboard checks cover sidebar arrow navigation, Escape/Tab behavior in
  overlays, route focus transfer, product-tour controls, and labelled icon
  buttons.
- Responsive checks cover source columns, Map controls, Chat evidence panel,
  onboarding, and Bridge wrapping without relying on brittle exact class-name
  strings.
- State checks cover persisted source view, suggestion dismissal/undo, focused
  cluster Map, failed-source recovery, status messaging, and URL-linked
  Settings sections.

Disposition notes:

- `UI-31` remains intentionally absent because the supplied audit skipped that
  number.
- `B-03` keeps suggested prompts as fill-without-auto-submit. This is a consent
  and editability choice, not a broken interaction.
- `B-12` keeps first-source inspector selection on desktop because the inspector
  is a persistent master-detail pane; selection is now stable and clearly
  visible.
- `B-19` (inline rename from the cluster list) and `B-21` (a dedicated save
  shortcut) remain P3 productivity enhancements. Rename is available in cluster
  detail and chats persist automatically, so neither blocks a primary task.
- `UI-29` is resolved through simpler progressive steps rather than forcing
  unrelated choices into one dense page. The number of visible decisions is
  less important than keeping each decision understandable and resumable.

### 18.9 Windows packaging and installed lifecycle

Implemented behavior:

- `package-logo.png` is converted reproducibly to the Windows icon used for the
  application executable, installer, uninstaller, shortcuts, and onboarding
  image asset.
- Packaging stages the Python runtime, backend, UI, browser payload, helper
  manifest, and managed llama runtime before Electron Builder runs.
- Shared llama archive caching is protected by a lock and each download uses a
  process-unique temporary file, preventing concurrent package runs from
  corrupting the archive.
- Electron staging retries/cleans only exact generated staging targets and
  verifies the expected unpacked executable and installer outputs.
- Package smoke tests use isolated data directories and explicit paths; they do
  not accidentally consume the developer's old `%APPDATA%` vault.
- The full-vault smoke follows the durable queued reindex contract, runs a job
  cycle, and then verifies semantic search, OCR image/PDF handling, query cache,
  and diagnostics.
- Installer verification can redirect temporary and installation paths to a
  drive with sufficient free space, then validates installed executable,
  desktop/start-menu shortcut targets, uninstall registry metadata, and silent
  uninstall.

Primary automated evidence:

- `scripts/packaging/validate-clean-machine-package.ps1`
- `scripts/packaging/smoke-packaged-runtime.ps1`
- `scripts/packaging/smoke-packaged-full-vault.ps1`
- `scripts/packaging/smoke-packaged-migration-drill.ps1`
- `scripts/packaging/smoke-packaged-app-launch.ps1`
- `scripts/packaging/smoke-windows-installer.ps1`
- `scripts/packaging/audit-package-layout.cjs`

Closed or materially addressed findings:

- `PKG-01` through `PKG-11`

## 19. Bugs Discovered During Implementation

The deeper implementation pass found additional failures that were not obvious
from the original screen-by-screen audit.

### NEW-01: Historical citations remained live after source deletion

Cause:

- Deleting a source removed the source but did not update encrypted citation
  records embedded in prior answers.

Risk:

- Historical answers could imply a deleted source still existed or retain stale
  protected metadata.

Fix:

- Mark matching encrypted citations as `source_deleted` in both ordinary and
  chat-owned source deletion paths.

Regression test:

1. Create a source and an answer with an encrypted citation.
2. Delete the source through each supported ownership path.
3. Reload history.
4. Assert the answer remains, citation state is `source_deleted`, no protected
   source payload is returned, and unrelated citations remain unchanged.

### NEW-02: Running jobs were labelled cancelled before the worker stopped

Cause:

- The cancel endpoint wrote terminal `cancelled` immediately even when a worker
  still owned the operation.

Risk:

- UI and recovery logic could report safety while the handler continued to
  mutate the vault.

Fix:

- Add `cancellation_requested` and `cancellation_requested_at`. Only the worker
  writes terminal cancelled after cooperative acknowledgement.

Regression test:

1. Start a blocking job with a controllable checkpoint.
2. Request cancellation while the handler is inside the checkpoint.
3. Assert status remains running and cancellation is requested.
4. Release the handler to observe cancellation.
5. Assert terminal cancelled is written once and no mutation occurs afterward.

### NEW-03: Concurrent packaging could contend on one shared archive

Cause:

- Llama runtime staging used a shared cache filename without a lock or unique
  download temporary path.

Risk:

- One build could hash or unpack a partially written archive from another build.

Fix:

- Serialize shared-cache population with a lock, download to a process-unique
  temporary file, verify it, and atomically publish it.

Regression test:

1. Launch two staging processes against an empty disposable cache.
2. Delay the first download mid-stream.
3. Assert the second waits or uses the completed verified archive.
4. Assert both staged manifests contain the expected hash and neither reads a
   partial file.

### NEW-04: MiniLM location resolver disagreed with the downloader

Cause:

- The downloader produced a named child/snapshot layout while activation checked
  only the selected root.

Risk:

- A completed download appeared missing and memory search remained unavailable.

Fix:

- Resolve direct, named-child, and Hugging Face snapshot layouts.

Regression test:

- Parameterize all three directory shapes, include one corrupt/incomplete shape,
  and require only complete model directories to activate.

### NEW-05: Embedding status performed heavyweight model initialization

Cause:

- Rendering status could import Torch and instantiate SentenceTransformers.

Risk:

- The onboarding page appeared frozen or reported the local service unavailable
  while a harmless status request exceeded its timeout.

Fix:

- Status is now a fast filesystem/configuration check; model loading belongs to
  the explicit activation/search path.

Regression test:

- Mock the SentenceTransformers constructor to fail if called, invoke status,
  and require a timely truthful response without constructor usage.

### NEW-06: Full-vault smoke expected obsolete synchronous reindex behavior

Cause:

- The smoke test expected reindex completion from the API response after the
  product moved to durable queued jobs.

Risk:

- A healthy package failed verification, or the smoke could skip validating the
  actual worker contract.

Fix:

- Assert a queued durable job, run one controlled worker cycle, and then verify
  semantic output.

Regression test:

- Run the packaged smoke against a fresh isolated vault and require both the job
  transition and resulting semantic search data.

### NEW-07: APPDATA isolation did not isolate Electron `userData`

Cause:

- Merely overriding process environment paths did not guarantee Electron's
  effective `userData` directory.

Risk:

- A “clean machine” smoke could reopen the developer's old vault and falsely
  pass or fail onboarding behavior.

Fix:

- App launch smoke passes `--user-data-dir` and watches the exact isolated
  runtime log.

Regression test:

- Seed the normal profile with a completed vault, launch with an empty explicit
  profile, and require `/onboarding` with no reference to the seeded vault.

### NEW-08: Interrupted migration still reported normal readiness

Cause:

- Startup repair recorded migration information but did not set degraded mode
  for interrupted/failed migration records.

Risk:

- Users could continue into a partially migrated vault believing it was healthy.

Fix:

- Startup repair sets `safe_degraded_mode=true` and emits a recovery issue for
  interrupted/failed migrations or migration-status read failure.

Regression test:

- Inject each migration state and a status-read exception; require degraded mode
  and a stable, actionable issue while preserving read-only diagnostics.

### NEW-09: Installer lifecycle failed because the system drive was full

Cause:

- Windows Installer used the system temporary/install drive, which had less than
  one gigabyte free on the test machine.

Risk:

- An environmental exit code could be misdiagnosed as a broken installer.

Fix:

- The lifecycle harness accepts explicit temporary and installation roots and
  reports disk availability before installation.

Regression test:

- Run once with an intentionally insufficient disposable target and require a
  preflight failure; run with sufficient space and validate install, shortcuts,
  registry metadata, launch path, and uninstall.

### NEW-10: A production PDF dependency had a known vulnerability

Cause:

- The packaged backend pinned `pypdf` 6.13.3.

Fix:

- Upgrade to 6.14.2 in the backend project and contributor requirements, then
  rebuild the bundled Python runtime.

Regression test:

- `pip check`, Python dependency audit, focused PDF ingestion tests, full
  backend tests, and a bundled-interpreter version assertion.

### NEW-11: NSIS used the nearly full system drive for build temporaries

Cause:

- Electron Builder's generated output was already isolated on the workspace
  drive, but `TEMP`/`TMP` still pointed at C:. NSIS needed a roughly 703 MB
  memory-mapped temporary file while C: had only about 641 MB free.

Risk:

- Three otherwise complete package attempts failed with NSIS internal compiler
  error `#12345`, even though the selected output drive had hundreds of
  gigabytes free.

Fix:

- The Windows package script creates a workspace-local builder temporary
  directory, scopes `TEMP` and `TMP` to it for Electron Builder/NSIS, and
  restores the caller's environment in `finally`.

Regression test:

1. Point the caller's `TEMP`/`TMP` at an intentionally constrained disposable
   volume.
2. Run packaging with the repository on a volume with sufficient space.
3. Assert the package log identifies the workspace builder temporary directory.
4. Assert NSIS completes, artifacts are published, and the caller's original
   environment values are restored.

### NEW-12: Packaged dependency pin drifted from the backend project

Cause:

- The package script duplicated backend dependency pins. `pyproject.toml` and
  contributor requirements were updated to `pypdf 6.14.2`, but the package
  script still requested 6.13.3. Its cache key was based on that stale duplicate
  list, so the cache appeared valid.

Risk:

- Local tests and dependency audit could pass while the shipped installer still
  contained the vulnerable version.

Fix:

- Align the packaged pin to 6.14.2, version the runtime cache contract, and
  include the complete backend project file in the cache fingerprint.

Regression test:

- `test_packaged_runtime_pypdf_pin_matches_backend_project` compares the package
  pin to the project dependency. The final package gate reads the distribution
  version from the bundled interpreter and requires 6.14.2.

## 20. Verification Results

### 20.1 Completed local gates

| Gate | Result |
| --- | --- |
| Final backend full suite | 789 passed, 2 skipped, 1 deprecation warning |
| Backend cancellation-focused suite | 12 passed |
| PDF ingestion tests after `pypdf` 6.14.2 | 8 passed |
| Desktop typecheck and Electron shell suite | 52 passed |
| Helper manifest suite | 2 passed |
| Renderer unsafe-HTML audit | Passed |
| Interactive-control audit across 41 TSX files | Passed |
| 50,000-file explicit scale gate | Passed |
| 10k-source/1k-chat/1k-cluster/10k-job scale gate | Passed |
| Python `pip check` | Passed |
| Python production dependency vulnerability audit | No known vulnerabilities |
| npm production dependency audit | 0 production vulnerabilities |
| Final bundled interpreter | `pypdf 6.14.2`; SentenceTransformers 5.5.1; Hugging Face Hub 1.24.0 |
| Final packaged runtime smoke | Passed |
| Final packaged full-vault smoke | Passed: semantic search, queued reindex, image OCR, scanned-PDF OCR, cache, diagnostics |
| Final packaged migration drill | Passed: interrupted migration enters safe degraded mode |
| Final isolated packaged app first-launch route | `/onboarding` |
| Final package layout audit | 500 manifest entries, no overlaps |
| Final clean-machine static validator | Passed |
| Final Windows installer lifecycle with sufficient T: space | Passed: install, shortcuts, registry, uninstall |

### 20.2 Final Windows artifacts

The final development/test package was produced from the dependency-updated
runtime:

| Artifact | Result |
| --- | --- |
| Unpacked application | `apps/desktop/release/win-unpacked/CML.exe` (201.2 MB) |
| NSIS installer | `apps/desktop/release/test-0.1.9-Setup.exe` (656.2 MB) |
| Installer SHA-256 | `414A080D0C9ABF0EF48285D17F60D3DB09C28B61C39FA9403BB9AA3592E17088` |
| Package duration | 21:25, including one-time 7:35 Python runtime cache refresh |
| Electron Builder attempt | First attempt passed with workspace-local `TEMP`/`TMP` |

The package emitted one non-fatal cleanup warning for the exact generated
Electron Builder output directory after artifacts had already been copied and
verified. It does not affect the published package and the directory is ignored
temporary build state.

### 20.3 Dependency-audit note

The production npm dependency audit is clean. The all-dependency audit reports
19 high-severity transitive findings in Electron Builder/ESLint build tooling.
The available automatic remediation is breaking. These packages are not shipped
as renderer/backend production dependencies, but the warning remains a build
supply-chain maintenance item and must not be described as “zero findings.”

### 20.4 CI scope

The local CI-equivalent gates above prove the working tree. Remote GitHub CI is
not evidence until the five requested commits are pushed and the resulting
workflow run completes. A remote result must be added here with its commit SHA;
local success must not be presented as a remote CI pass.

## 21. Requirement-to-Test Release Checklist

Use this checklist for the final release decision.

| Requirement | Release-blocking proof |
| --- | --- |
| Fresh install opens onboarding | Isolated explicit `userData` packaged launch |
| Interrupted onboarding resumes correctly | Setup-state unit and rendered transition tests |
| Wrong backend is never reused | Descriptor mismatch/restart rollback test |
| New unsecured vault is unlocked | Per-vault unlock integration test and packaged setup |
| Existing secured data is migrated | Protected-plaintext marker test and migration drill |
| Vault move/delete cannot strand state | Fault-injection rollback and authorization tests |
| Model state is truthful | Supervised runtime health plus live generation probe |
| Model file is trusted | SHA-256 missing/mismatch/success tests |
| Downloads are real-time and durable | Byte-progress, restart, resume, and cancel tests |
| MiniLM is consensual and usable | Consent UI, worker, path-layout, packaged import tests |
| Stream always terminates | EOF/stop/disconnect/error generation tests |
| Cancelled work stops before terminal state | Worker acknowledgement/no-late-mutation test |
| Large vault remains correct | Explicit scale fixtures and server aggregate tests |
| Optional failures do not erase primary UI | Route boundary and stale-response tests |
| Onboarding matches reference geometry | Rendered geometry at target and constrained sizes |
| Product tour is one-time and accessible | Durable tour state and keyboard Playwright test |
| Logo appears everywhere required | Extracted exe/installer/uninstaller/shortcut icon check |
| Package contains all runtimes | Manifest/layout and bundled-interpreter checks |
| Installer and uninstall work | Isolated lifecycle test with shortcut/registry assertions |

## 22. Commands for Developers

From the repository root:

```powershell
# Desktop compile and shell tests
npm run lint

# Full backend suite
.\.venv\Scripts\python.exe -m pytest backend\tests

# Explicit scale suite
$env:CML_RUN_SCALE_TESTS = "1"
.\.venv\Scripts\python.exe -m pytest backend\tests\test_odin_scale.py -m benchmark
Remove-Item Env:\CML_RUN_SCALE_TESTS

# Build the Windows development installer and unpacked application
npm run package:win
```

Expected Windows outputs:

- `apps/desktop/release/test-0.1.9-Setup.exe` — development NSIS installer.
- `apps/desktop/release/win-unpacked/CML.exe` — unpacked application executable.

The unpacked executable is the runnable application, not a second installer.
