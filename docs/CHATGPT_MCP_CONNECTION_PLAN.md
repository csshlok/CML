# ChatGPT MCP Connection Implementation Plan

## 1. Objective

Enable Vault users to connect their selected libraries and clusters to ChatGPT through a supported MCP connection without making the local Vault backend publicly reachable.

The default production path will use OpenAI Secure MCP Tunnel:

```text
ChatGPT
  -> OpenAI-hosted tunnel endpoint
  -> tunnel-client on the Vault device
  -> packaged Vault MCP server over stdio
  -> authenticated loopback Vault backend
```

An optional future deployment path may expose a hosted Streamable HTTP endpoint:

```text
ChatGPT or Responses API
  -> public HTTPS /mcp
  -> remote Vault MCP gateway
  -> authenticated Vault service
```

The tunnel path is the first target because Vault is local-first and already has a stdio MCP implementation.

## 2. Current State

Vault currently provides:

- A JSON-RPC MCP server in `backend/app/bridge_mcp.py`.
- MCP initialization, `tools/list`, and `tools/call`.
- Read tools for clusters and source-grounded context.
- Write tools for saving transcripts and artifacts.
- Review tools for gated writeback.
- Per-client Vault Bridge tokens and vault/cluster allowlists.
- Development configuration for Claude Desktop and Cursor.

Current gaps:

- The setup command depends on `.venv\Scripts\python.exe` and a source checkout.
- There is no packaged MCP launcher.
- There is no ChatGPT connection type in Bridge.
- Vault does not install, launch, monitor, or configure `tunnel-client`.
- Tool definitions do not include MCP safety annotations.
- There is no ChatGPT plan/capability-aware read-only mode.
- There is no tunnel health, reconnect, or revocation UI.
- No ChatGPT tool-scan or end-to-end test exists.
- Bridge status incorrectly reports MCP as `planned`.
- There is no supported public Streamable HTTP `/mcp` transport.

## 3. Scope

### In scope

- Secure MCP Tunnel integration for packaged desktop builds.
- Packaged stdio MCP process lifecycle.
- ChatGPT-specific setup and status UX.
- Read-only and read/write capability modes.
- Tool annotations, schemas, pagination, limits, and error contracts.
- Local token handling, tunnel identity, revocation, audit history, and approvals.
- Reliability, backpressure, reconnect, cancellation, and observability.
- Automated protocol, security, fault, performance, packaging, and end-to-end tests.

### Not in the first release

- Hosting user vault contents in a CML cloud service.
- A public multi-tenant MCP endpoint.
- Automatic workspace administration or publication inside ChatGPT.
- Storing OpenAI API keys in Vault.
- Bypassing ChatGPT workspace permissions or plan restrictions.
- Interactive Apps SDK UI rendered inside ChatGPT.

## 4. Architecture Decisions

### 4.1 Default transport

Use Secure MCP Tunnel with the existing stdio server. Do not expose the loopback backend or its bearer token to the network.

The tunnel process receives:

- Tunnel identity and runtime credentials through a secure local credential store.
- A packaged command for launching the Vault MCP server.
- A local working directory owned by the application.
- A short-lived, scoped Bridge client token passed only to the child process.

### 4.2 Process boundaries

Create three explicit processes:

1. Electron desktop process owns setup, user consent, and lifecycle.
2. `tunnel-client` owns the outbound HTTPS connection to OpenAI.
3. Vault MCP server owns MCP framing and forwards authorized calls to the loopback backend.

The MCP process must never inherit unrelated environment secrets.

### 4.3 Transport abstraction

Refactor MCP tool definitions and handlers into a transport-independent module:

- `bridge_mcp_tools.py`: schemas, annotations, validation, and dispatch.
- `bridge_mcp_stdio.py`: newline-delimited JSON-RPC stdio adapter.
- Future `bridge_mcp_http.py`: optional Streamable HTTP adapter.

This prevents tool behavior from diverging between stdio, tunnel, inspector, and future HTTP deployments.

### 4.4 Capability profiles

Define explicit profiles:

- `read_only`: list clusters, retrieve context, expand context, list captures/reviews.
- `read_write`: read tools plus transcript/artifact capture and review decisions.

The selected profile is enforced by the backend, not only hidden in the UI or tool list.

ChatGPT plan availability changes over time. Vault must describe the two modes without hard-coding an entitlement promise. The user selects the capability their ChatGPT workspace permits, and Vault verifies the tools returned during scan.

## 5. MCP Contract Changes

### 5.1 Protocol behavior

- Negotiate a supported MCP protocol version instead of returning one fixed version without checking the client request.
- Handle notifications without responses.
- Return valid JSON-RPC IDs for all request errors.
- Support graceful shutdown and end-of-input.
- Cap inbound message size before JSON decoding.
- Reject duplicate in-flight request IDs.
- Add cancellation support when supported by the negotiated protocol.
- Emit stable application error codes and safe user-facing messages.

### 5.2 Tool metadata

Every tool must provide:

- Stable name.
- Concise description.
- Strict JSON Schema with `additionalProperties: false`.
- Required fields and bounded lengths.
- MCP annotations such as read-only, destructive, idempotent, and open-world behavior.
- A capability profile.
- A semantic version for breaking-change review.

Proposed annotations:

| Tool | Read-only | Destructive | Idempotent |
|---|---:|---:|---:|
| `list_clusters` | Yes | No | Yes |
| `get_cluster_context` | Yes | No | Yes |
| `expand_context_item` | Yes | No | Yes |
| `list_captures` | Yes | No | Yes |
| `list_writeback_reviews` | Yes | No | Yes |
| `log_external_turn` | No | No | Conditional with idempotency key |
| `capture_external_artifact` | No | No | Conditional with idempotency key |
| `decide_writeback_review` | No | Potentially | Conditional with expected review state |

### 5.3 Schema and payload limits

- Replace unrestricted numeric values with bounded integers.
- Add maximum string lengths to every field.
- Add cursor-based pagination for list tools.
- Limit context packets by bytes and tokens, not just record count.
- Truncate or summarize oversized source excerpts with explicit metadata.
- Reject binary or NUL-containing strings.
- Normalize vault and cluster identifiers.
- Add optional `request_id`/`idempotency_key` for writes.
- Return typed content and structured results where supported.

### 5.4 Stable error taxonomy

Use stable error codes:

- `bridge_disabled`
- `client_revoked`
- `scope_denied`
- `capability_denied`
- `no_active_vault`
- `vault_locked`
- `vault_missing`
- `cluster_missing`
- `approval_required`
- `request_too_large`
- `rate_limited`
- `backend_unavailable`
- `backend_timeout`
- `tunnel_unavailable`
- `conflict`
- `internal_error`

Errors must include:

- Safe summary.
- Retriable boolean.
- Optional retry delay.
- Correlation ID.
- No filesystem paths, bearer tokens, stack traces, or source contents.

## 6. Packaged Runtime

### 6.1 MCP launcher

- Package the MCP entry point with the same signed Python runtime as the backend.
- Add an Electron IPC method that returns a versioned launcher descriptor.
- Use absolute packaged paths resolved by Electron.
- Avoid `.venv`, repository-relative paths, shell expansion, and user-controlled commands.
- Restrict the child environment to the backend URL, scoped token, API prefix, locale, and required runtime paths.
- Verify packaged helper integrity before launch.
- Capture bounded stdout/stderr diagnostics without logging secrets.

### 6.2 Tunnel client

- Pin and package a reviewed `tunnel-client` version or securely download a signed release.
- Verify checksum/signature before first execution.
- Store runtime credentials in the OS credential store.
- Run it as a hidden child process owned by Electron.
- Use exponential backoff with jitter.
- Stop retrying on permanent authentication or permission errors.
- Shut down on user disconnect, Vault exit, profile reset, or token revocation.
- Detect orphaned processes after crashes and reconcile them at startup.
- Never bind an inbound public port.

### 6.3 Updates and compatibility

- Maintain a compatibility matrix for Vault, MCP protocol, and tunnel-client versions.
- Refuse incompatible upgrades with a clear recovery action.
- Preserve existing Claude/Cursor stdio configuration.
- Migrate Bridge settings with an explicit schema version.
- Rotate scoped tokens after upgrades that change permissions.

## 7. Authentication and Authorization

### 7.1 Tunnel identity

- Treat the OpenAI tunnel identity and Vault Bridge client identity as separate trust layers.
- Associate one Vault client record with one tunnel connection.
- Generate a one-time enrollment secret.
- Exchange it for a scoped local Bridge token.
- Never display the token after enrollment.
- Support rotate, revoke, disconnect, and reconnect.

### 7.2 Vault authorization

Enforce on every call:

- Bridge enabled.
- Client active and not expired/revoked.
- Requested vault allowed.
- Requested cluster allowed.
- Capability profile permits the tool.
- Vault is present and unlocked where required.
- Write approval rules are satisfied.

Do not trust a vault or cluster ID simply because it came from a prior tool response.

### 7.3 Write safety

- Require ChatGPT approval plus Vault policy approval for sensitive writes.
- Default new ChatGPT connections to read-only.
- Give write tools accurate destructive/idempotency annotations.
- Use idempotency keys to prevent duplicate artifacts after retry.
- Use optimistic state/version checks for review decisions.
- Preserve a local audit event for every attempted write, including denials.
- Provide an emergency “Disconnect and revoke” action.

### 7.4 Threat model requirements

Test and document:

- Prompt injection contained in vault sources.
- Tool-description injection.
- Scope escalation through guessed IDs.
- Replay of old tunnel requests.
- Stolen enrollment link or runtime credential.
- Token leakage through process listings, logs, crash reports, or diagnostics.
- Symlink/path traversal in packaged launcher resolution.
- SSRF through user-controlled URLs.
- Oversized JSON and decompression/resource exhaustion.
- Malicious Unicode, control characters, and schema confusion.
- Write retry duplication.
- Approval race conditions.

## 8. Desktop UX

### 8.1 Bridge overview

Replace ambiguous service language with:

- Connection state: Not connected, Connecting, Connected, Attention required, or Disconnected.
- Client: ChatGPT, Claude Desktop, Cursor, or Other.
- Access: Read-only or Read and save.
- Scope: selected libraries and clusters.
- Last successful request.
- Last error with a specific recovery action.

Correct backend status so implemented MCP no longer reports `planned`.

### 8.2 ChatGPT setup flow

Add a ChatGPT option with these steps:

1. Explain supported workspace/plan limitations without claiming eligibility.
2. Choose read-only or read/write capability.
3. Choose allowed libraries and clusters.
4. Sign in to or enroll the OpenAI tunnel.
5. Start the local tunnel and run a health check.
6. Show the endpoint/connection in a copy-safe form.
7. Guide the user through ChatGPT developer mode and tool scanning.
8. Run a harmless `list_clusters` verification.
9. For write mode, run an explicit test artifact requiring confirmation and then remove it.
10. Show connection completion and revocation instructions.

The setup must be resumable after restart and must not expose credentials in screenshots or clipboard history unnecessarily.

### 8.3 Failure UX

Provide distinct recovery for:

- ChatGPT plan does not allow requested write tools.
- Developer mode unavailable.
- Tunnel permission denied.
- Tunnel authentication expired.
- Vault locked.
- Vault deleted or moved.
- Local backend offline.
- Tool scan rejected due to schema or annotations.
- Tunnel connected but no library allowed.
- Connection revoked from ChatGPT or Vault.
- Version mismatch.
- Rate limiting.

Every busy button must reset in `finally`, except after confirmed navigation or process replacement.

## 9. Reliability and Scaling

### 9.1 Concurrency

- Bound concurrent MCP calls per client and globally.
- Use separate limits for retrieval and writes.
- Queue only bounded work; reject excess with `rate_limited`.
- Propagate cancellations to retrieval and backend HTTP calls.
- Do not let a slow context request block health checks or lightweight list calls.
- Use a semaphore around expensive retrieval/model work.

### 9.2 Backpressure and payloads

- Cap stdin line length and decoded JSON size.
- Cap tool output bytes and token estimates.
- Stream only where the client and tunnel support it.
- Avoid buffering full large context packets more than once.
- Paginate histories and clusters.
- Add timeouts for backend connect, first byte, idle response, and total call duration.

### 9.3 Multi-client and multi-vault behavior

- Use a distinct client identity, scope, rate bucket, and audit trail per connection.
- Prevent cross-client cache leakage.
- Include vault and scope version in cache keys.
- Invalidate permissions within seconds after revoke or scope change.
- Define deterministic behavior when the active vault changes.
- Return `vault_locked` or `vault_missing` instead of silently switching vaults.

### 9.4 Provisional performance targets

Validate these targets on supported minimum hardware before freezing them:

- MCP initialization and tool listing: p95 under 1 second locally.
- Lightweight list call: p95 under 500 ms for 10,000 clusters with pagination.
- Tunnel reconnect after transient loss: p95 under 15 seconds.
- Permission revoke propagation: under 5 seconds.
- Memory growth: bounded during a 24-hour idle tunnel and a 1,000-call soak.
- No unbounded queue, log file, cache, or retry growth.

Context retrieval latency depends on vault size and embedding hardware. Measure it separately and show progress/timeout messaging rather than promising a universal latency.

### 9.5 Observability

Record structured, redacted events:

- Connection state transitions.
- Tunnel reconnect reason and backoff.
- Tool name, client ID, scope hash, duration, result class, and correlation ID.
- Payload size buckets, not payload contents.
- Rate-limit and timeout counts.
- Approval and revocation decisions.

Diagnostics must redact:

- Tunnel credentials.
- Bridge tokens.
- OpenAI/API authorization headers.
- Source text and prompts by default.
- User paths and identifiers where not necessary.

## 10. Testing Plan

### 10.1 Unit tests

- MCP initialization negotiation.
- Notifications and request IDs.
- Tool schemas and annotations snapshot.
- Strict validation and size bounds.
- Capability profile filtering.
- Error-code mapping and redaction.
- Idempotency and optimistic review decisions.
- Token rotation, revoke, and expiration.
- Backoff/jitter state machine.
- Packaged launcher path and environment construction.

### 10.2 Contract tests

Run the official/community MCP Inspector against:

- Development stdio server.
- Packaged stdio server.
- Secure tunnel endpoint.
- Future Streamable HTTP adapter.

Assert:

- Initialization succeeds for supported protocol versions.
- Tools scan successfully.
- JSON Schemas are accepted.
- Annotations match security policy.
- Read-only profile cannot discover or call write tools.
- Breaking schema changes are caught by snapshots.

### 10.3 Backend integration tests

- Every tool against real temporary SQLite vaults.
- Locked, deleted, moved, and corrupted vault behavior.
- Client scope changes during an active request.
- Backend restart during a tool call.
- Duplicate/replayed writes.
- Concurrent review decisions.
- Pagination stability while records are added.
- Retrieval cancellation and timeouts.
- Rate limiting by client and globally.

### 10.4 Electron integration tests

- Packaged path resolution on Windows.
- Child environment contains no unrelated secrets.
- Start, stop, restart, crash recovery, and orphan cleanup.
- Credential-store round trip without plaintext persistence.
- App quit and setup reset terminate the tunnel.
- Scope changes rotate or refresh credentials safely.
- UI buttons recover after every failure path.

### 10.5 ChatGPT end-to-end matrix

Test in supported ChatGPT web workspaces:

| Scenario | Read-only | Read/write |
|---|---:|---:|
| New connection and tool scan | Required | Required |
| Invoke direct tool by name | Required | Required |
| Natural-language tool selection | Required | Required |
| Approval prompt behavior | N/A | Required |
| Revoke from Vault | Required | Required |
| Revoke from ChatGPT | Required | Required |
| Vault locked/missing | Required | Required |
| Tunnel reconnect | Required | Required |
| Updated tool schema snapshot | Required | Required |

Also verify the documented restricted-plan behavior. The UI must downgrade gracefully to read-only when write actions are unavailable.

### 10.6 Security tests

- Fuzz JSON-RPC framing and schemas.
- Attempt cross-vault and cross-cluster access.
- Inject tokens into logs and verify redaction.
- Simulate prompt-injected tool instructions from source content.
- Replay write calls and enrollment material.
- Validate child-process executable integrity.
- Test malicious environment variables and command arguments.
- Verify no non-loopback backend listener is introduced.
- Run dependency and secret scans on tunnel packaging.

### 10.7 Fault-injection tests

Inject:

- Offline network.
- DNS failure.
- TLS and certificate errors.
- Tunnel 401/403/429/5xx responses.
- Partial/stalled stdio messages.
- Backend connection reset.
- Process crash before and after credential rotation.
- Disk full and read-only credential storage.
- System sleep/resume and clock changes.
- Rapid connect/disconnect clicks.
- Two app instances competing for the same tunnel.

### 10.8 Performance and soak tests

- 1,000 sequential tool calls.
- Bounded concurrent calls at 1x, 2x, and overload capacity.
- 24-hour idle tunnel with reconnects.
- Large-vault pagination with at least 10,000 clusters/sources.
- Maximum allowed context packet.
- Repeated cancellation and timeout cleanup.
- Memory, handles, subprocesses, logs, and SQLite connection counts.

### 10.9 Upgrade and rollback tests

- Upgrade from existing Claude/Cursor Bridge settings.
- Upgrade while a tunnel is connected.
- Downgrade with newer settings present.
- Token and scope preservation rules.
- Roll back tunnel-client version.
- Reset setup without deleting downloaded models.
- Delete vault while tunnel is active.

## 11. Rollout Strategy

1. Land transport-independent tool contracts behind a feature flag.
2. Add packaged stdio launcher and Inspector coverage.
3. Add tunnel lifecycle with an internal-only UI.
4. Complete security review and fault/soak tests.
5. Enable read-only ChatGPT connections for a small test cohort.
6. Measure scan success, connection stability, latency, and support failures.
7. Add read/write mode after approval/idempotency tests pass.
8. Expand availability with a kill switch and version rollback.

Feature flags:

- `chatgpt_mcp_setup`
- `secure_mcp_tunnel`
- `chatgpt_mcp_write_tools`
- `mcp_streaming`
- `mcp_remote_http` (future)

## 12. Release Gates

Do not release until:

- Packaged MCP server passes Inspector and ChatGPT tool scan.
- No `.venv` or repository path is required.
- Read-only clients cannot call write tools at either MCP or backend layers.
- Tokens and tunnel credentials are absent from logs, diagnostics, process arguments, and setup screenshots.
- Revoke propagation and emergency disconnect pass.
- Retry cannot duplicate a write.
- Locked, missing, moved, and deleted vaults return correct errors.
- Tunnel crash/reconnect and app restart recovery pass.
- Overload is bounded and observable.
- 24-hour soak shows no material memory, handle, process, or log growth.
- Security review signs off on prompt injection, scope enforcement, secret handling, and packaging.
- User documentation identifies supported ChatGPT surfaces without guaranteeing account eligibility.

## 13. Definition of Done

A release is complete when a packaged Vault user can:

1. Open Bridge and choose ChatGPT.
2. Select read-only or read/write access.
3. Select explicit libraries and clusters.
4. Establish a Secure MCP Tunnel without using a terminal or source checkout.
5. Add/scan the connection in a supported ChatGPT workspace.
6. Ask ChatGPT to list clusters and retrieve grounded context.
7. Use writeback only after the required approvals.
8. See actionable connection and vault errors.
9. Revoke the connection immediately from Vault.
10. Export redacted diagnostics that are sufficient to debug connection failures.

All automated, security, packaging, fault-injection, performance, soak, upgrade, and ChatGPT end-to-end release gates must pass.

---

## 14. Application Reliability Remediation Program

### 14.1 Purpose and relationship to the MCP release

The codebase audit performed against `docs/bugs&changes.md` and the supplied startup/model report found application-wide reliability problems that also affect the MCP connection. The tunnel and MCP server cannot be considered production-ready while the desktop can remain invisible during startup, packaged hardware detection can reject every supported model, long operations are represented as failed requests after twelve seconds, or shared polling and loader failures can leave the UI stale.

This section is the consolidated implementation plan for:

- Previously identified defects from the broad codebase scan.
- Defects reproduced or confirmed during the startup/model investigation.
- Additional defects found while tracing the same architectural patterns.
- Stale report items that need regression coverage but no current implementation change.

The work below is part of the release-critical path for Sections 11 through 13. Items marked P0 or P1 must be completed before the ChatGPT MCP rollout reaches a user cohort.

### 14.2 Confirmed issue inventory

| ID | Priority | Area | Confirmed problem | Primary impact |
|---|---|---|---|---|
| REL-001 | P0 | Packaged models | The packaged Python runtime omits the dependencies used to detect RAM, producing an `unknown` hardware tier that rejects all approved model families. | Capable devices cannot import or activate GGUF models. |
| REL-002 | P0 | Startup UX | Electron waits for full backend readiness before constructing or showing a window. | Cold starts look like the app did not launch. |
| REL-003 | P0 | Startup integrity | All 500 packaged helper files, currently about 1.255 GiB, are SHA-256 hashed serially on every launch. | Severe cold-start disk and antivirus amplification. |
| REL-004 | P0 | Backend startup | Eager route imports, full SQLite integrity checking, migrations, recovery, reconciliation, and model detection all precede readiness. | Backend readiness is unnecessarily coupled to optional work. |
| REL-005 | P0 | Request lifecycle | One twelve-second frontend timeout applies to lightweight reads and multi-gigabyte copies or whole-drive scans alike. | False failures, duplicate retries, and server work continuing after the UI gives up. |
| REL-006 | P1 | Model discovery | Discovery omits the active vault and selected model folder but scans all drive roots recursively by default. | Existing models are missed while unrelated disks are scanned. |
| REL-007 | P1 | Model classification | GPU capability is collected after CPU/RAM tier selection and nominal 16 GB machines fall below a strict 16 GiB boundary. | Capable machines are under-classified. |
| REL-008 | P1 | Background jobs | Startup always queues vector reconciliation even when embeddings are unavailable; the missing prerequisite is treated as a retryable execution failure. | Expected setup state is shown as a failed maintenance job. |
| REL-009 | P1 | Local images | Profile and source images are converted to `file:` URLs while renderer CSP blocks `file:`; the sidebar ignores the configured profile image. | Selected images never render consistently. |
| REL-010 | P1 | Settings reliability | Settings loads many independent endpoints through all-or-nothing `Promise.all` polling every six seconds. | One failing endpoint makes the entire page stale or unavailable. |
| REL-011 | P1 | Shared async behavior | `useVisiblePolling` and `ConfirmAction` discard rejected promises. | Unhandled rejections, missing feedback, and unclear destructive-action outcomes. |
| REL-012 | P1 | Health state | Health checks can race, and changing the backend URL does not reliably publish a new connection state. | Stale or contradictory health indicators. |
| REL-013 | P1 | Loader isolation | Chat, clusters, sources, projects, search, tasks, and command-palette loaders commonly combine unrelated requests with `Promise.all`. | Partial backend degradation becomes a full-screen failure. |
| REL-014 | P1 | Pagination | Chat sessions, timelines, clusters, activity, and other lists have backend caps that renderer consumers do not paginate through. | Older data silently disappears. |
| REL-015 | P1 | Derived UI data | Saved chats, recent chats, and cluster activity are derived from bounded list responses. | Sidebar state and counts can be incorrect for larger vaults. |
| REL-016 | P1 | Query efficiency | Semantic-search result hydration performs per-result HTTP work, while several backend paths perform per-row SQL lookups. | Latency grows linearly and can cross frontend timeouts. |
| REL-017 | P2 | Window layout | Desktop chrome reserves a separate blank 32-pixel row. | Persistent wasted space and visual discontinuity. |
| REL-018 | P2 | Error placement | Model actions write into one shared Settings status message far from the control, with stale “Transformers checkpoint” terminology. | Users miss actionable errors and receive misleading instructions. |
| REL-019 | P1 | Odin distribution | Packaged builds claim to expose `odin`, but packaging does not install an executable or wrapper. | `odin auth pair` is not recognized in a normal packaged environment. |
| REL-020 | P2 | Odin architecture | The current CLI requires a live desktop runtime descriptor and is not a standalone `uv tool` despite the requested workflow. | Documentation and product expectations do not match the implementation. |
| REL-021 | P1 | Startup status | Startup status JSON is overwritten in place and has no phase durations. | Readers can observe malformed intermediate state and diagnostics cannot locate slow phases. |
| REL-022 | P2 | Test fidelity | Some tests assert source-code text or obsolete exception behavior instead of user-visible/runtime contracts. | Legitimate refactors fail while packaging and latency regressions escape. |

### 14.3 Resolved or non-reproducible report items

These items do not require a new implementation in the current tree, but they require regression tests:

- The sidebar and onboarding use the shared `BrandLogo` component. Add a component test that asserts the same asset and variant are used in both locations.
- A replayable Vault tour is available in Profile settings. Add a navigation test that starts, exits, and restarts the tour.
- `odin auth pair` exists in the parser and backend authorization flow. The unresolved defect is distribution and discoverability, not command implementation.

Do not reopen these items based only on old screenshots. Reopen them only if packaged UI or end-to-end tests reproduce a mismatch.

## 15. Implementation Workstreams

### 15.1 Workstream A: Immediate and measurable startup

Addresses REL-002, REL-003, REL-004, and REL-021.

#### Desktop startup changes

1. Construct the `BrowserWindow` before calling `ensureBackend()`.
2. Load a local startup renderer that does not require the backend.
3. Show the window as soon as the renderer is paintable.
4. Publish structured startup phase events from Electron to the renderer:
   - `desktop_initializing`
   - `runtime_verifying`
   - `backend_spawning`
   - `database_opening`
   - `core_ready`
   - `warming`
   - `ready`
   - `failed`
5. Allow the startup renderer to show recovery actions for lock failures, corrupted runtime files, backend exit, and timeout.
6. Replace the single 90-second silent wait with phase-aware progress and a user-visible diagnostic action.

#### Helper verification changes

1. Split the manifest into:
   - Critical launch files that must be verified synchronously.
   - Deferred runtime files verified after core readiness.
2. Add a signed, versioned verification receipt containing:
   - Application version.
   - Manifest hash.
   - Package identity/build hash.
   - Verification completion time.
3. Reuse the receipt only when the immutable package identity and manifest hash match.
4. Invalidate the receipt on update, repair, package relocation where identity cannot be proven, or manifest change.
5. Bound deferred verification concurrency to avoid saturating disk and antivirus scanners.
6. Fail closed before using any helper whose verification has not completed.
7. Record file count, byte count, cache hit/miss, and phase duration without logging user paths.

This optimization must preserve the integrity guarantee; size/mtime alone is not a trust decision.

#### Backend readiness changes

Define two readiness levels:

- `core_ready`: authentication, vault lock, database open, required migrations, schema compatibility, and lightweight health routes are available.
- `fully_ready`: optional reconciliation, model restoration, full maintenance, and warm caches are complete.

Implementation:

1. Move route imports that pull model, OCR, project, benchmark, or integration subsystems behind module-local imports or service registration.
2. Run `PRAGMA quick_check` during normal startup.
3. Run full `PRAGMA integrity_check`:
   - After an unclean shutdown when policy requires it.
   - During explicit diagnostics/repair.
   - On a scheduled maintenance cadence.
4. Keep migrations that are required for safe reads/writes before `core_ready`.
5. Move reconciliation planning, optional runtime detection, and model restore after `core_ready`.
6. Ensure background warming cannot mutate data through a schema version the core service has not accepted.
7. Emit monotonic start/end/duration fields for every phase.

#### Startup status durability

1. Write status to a sibling temporary file.
2. Flush and atomically replace the destination.
3. Include:
   - Startup instance ID.
   - Sequence number.
   - Phase start time.
   - Phase elapsed milliseconds.
   - Total elapsed milliseconds.
   - Readiness level.
4. Make the reader retain the last valid payload if a new payload cannot be decoded.

#### Acceptance criteria

- A visible startup window appears within 1 second on the supported minimum Windows hardware.
- Warm launch reaches `core_ready` at a measured p95 target agreed from baseline data.
- No unchanged helper payload is rehashed on every launch.
- Corrupt critical helpers are rejected before execution.
- Corrupt deferred helpers are rejected before first use and produce an actionable repair message.
- Full integrity checking is still available and scheduled.
- Diagnostics can attribute startup time to individual phases.

### 15.2 Workstream B: Correct packaged hardware and model management

Addresses REL-001, REL-006, REL-007, and REL-018.

#### Packaged hardware detection

1. Add `psutil` as an explicit, pinned backend and packaging dependency, or replace it with a tested native implementation.
2. Add the selected dependency to:
   - `backend/pyproject.toml`
   - Packaging runtime package lists
   - Runtime fingerprinting
   - Clean-machine validation
   - Software bill of materials and dependency audit
3. Keep the Windows AVX2 fallback.
4. Add a native Windows memory fallback so a missing optional library cannot silently become “unsupported.”
5. Change compatibility outcomes to three states:
   - `supported`
   - `unsupported`
   - `detection_failed`
6. Never convert `detection_failed` to a minimum-contract rejection message.

#### Hardware tiers

1. Calculate GPU inventory before selecting the hardware tier.
2. Define model eligibility from explicit resource requirements rather than a single opaque tier:
   - CPU instruction support.
   - Logical CPU count where relevant.
   - Total and currently available system memory.
   - Dedicated and shared GPU memory.
   - Runtime backend support for the detected GPU.
3. Account for firmware/reserved-memory loss on marketed 8/16/24/32 GB machines.
4. Use usable-memory safety margins for runtime selection without downgrading the device solely because reported binary GiB is slightly below the marketed boundary.
5. Explain which requirement failed and show detected values.

#### Discovery roots and indexing

1. Persist the user-selected model directory as application state.
2. Include these roots by default:
   - Managed model directory.
   - Persisted user-selected download/import directory.
   - Explicitly approved external model directories.
   - Optionally, the active vault parent when the user grants that scope.
3. Remove automatic recursive scanning of every drive root.
4. Offer an explicit “Search this drive” action with:
   - Scope preview.
   - Cancellation.
   - Progress.
   - Directory and file counters.
5. Maintain a lightweight model index keyed by canonical path, size, modification identity, and last compatibility result.
6. Invalidate entries on observed changes; do not rerun hardware detection for every candidate.
7. Exclude known system, cache, recycle-bin, package, and permission-denied directories.
8. Return partial results and scan warnings instead of failing the whole scan.

#### Model action UX

1. Place validation, scan, import, and activation results adjacent to the relevant control.
2. Use distinct status state for each action rather than the page-wide `statusMessage`.
3. Replace “Transformers checkpoints” with “GGUF models.”
4. Show `detection_failed` separately from an incompatible model.
5. Keep progress visible after navigation and app restart for job-backed operations.

#### Acceptance criteria

- The packaged runtime correctly reports RAM on clean Windows machines.
- The audit machine classifies at least the approved Qwen 4B family as supported.
- A GGUF in a persisted selected directory is rediscovered after restart.
- An ordinary model scan never traverses unapproved drive roots.
- Detection, scan, import, and activation errors render beside the initiating control.
- Hardware tests cover no-`psutil`, nominal-memory-boundary, CPU-only, supported GPU, and unknown-GPU cases.

### 15.3 Workstream C: Long-running operation and timeout architecture

Addresses REL-005 and the timeout-related portion of REL-016.

#### Request policy

Replace the single global timeout with typed request policies:

- Fast health/configuration reads: short connect and total timeout.
- Ordinary paginated reads: bounded total timeout with cancellation.
- Mutations that complete synchronously: operation-specific timeout.
- Long work: submit a job and return immediately.
- Streaming generation: connect, first-event, idle-event, and overall safety timeouts.

The backend client must map failures to stable categories:

- Backend unavailable.
- Connection timeout.
- Response timeout.
- User cancellation.
- Server cancellation.
- Validation error.
- Conflict.
- Job accepted and still running.

#### Convert long synchronous endpoints to jobs

At minimum:

- Model import/copy.
- Broad model discovery.
- Model verification where hashing is substantial.
- Diagnostic bundle creation.
- Vector repair/reindex.
- Maintenance batches.
- Integration refresh/import.
- Any run-once endpoint capable of executing multiple queued jobs.

Each job must provide:

- Durable ID and idempotency key.
- State, progress, current phase, and bounded status detail.
- Cancellation request and acknowledgement.
- Retry policy based on error category.
- Restart recovery behavior.
- Final artifact/result reference.

#### Client behavior

1. Never automatically retry a non-idempotent mutation after a timeout.
2. When submission acknowledgement is uncertain, query by idempotency key.
3. Preserve job state in the UI across navigation and restart.
4. Abort backend work when the operation is truly cancellable and the client cancels.
5. Tell the user whether work stopped, continues in the background, or could not be confirmed.

#### Acceptance criteria

- Importing a multi-gigabyte GGUF does not produce a false twelve-second failure.
- Retrying after a dropped response cannot duplicate a copy or mutation.
- Model scans and diagnostics expose progress and cancellation.
- Fast health calls are not blocked behind long jobs.
- Timeout errors identify the failed phase and recovery action.

### 15.4 Workstream D: Background-job prerequisites and state semantics

Addresses REL-008.

1. Represent embedding availability as a scheduler prerequisite or explicit capability gate.
2. Do not enqueue vector reconciliation at startup when no embedding provider is configured.
3. If embeddings become unavailable after enqueue:
   - Mark the job `blocked_setup_required` or `deferred`.
   - Do not consume retry attempts.
   - Store a safe prerequisite reason.
4. When embeddings become ready, wake or enqueue one deduplicated reconciliation job.
5. Separate:
   - Execution failure.
   - Dependency failure.
   - User cancellation.
   - Setup required.
   - Resource deferral.
6. Make job policy fields enforceable; do not leave `dependency_failure_policy` as descriptive metadata.
7. Update Tasks and Health to hide internal successful maintenance noise while showing actionable setup blockers.

Acceptance criteria:

- Starting without embeddings creates no failed vector job.
- Enabling embeddings triggers one reconciliation.
- Repeated restarts do not create duplicate reconciliation work.
- Disabling embeddings during a run produces a deferred/setup state, not a misleading failure.

### 15.5 Workstream E: UI resilience and local media

Addresses REL-009 through REL-013, REL-017, and REL-018.

#### Secure local media

1. Do not add broad `file:` access to renderer CSP.
2. Copy profile images into an application-owned media directory or expose approved files through a secure custom protocol/preload method.
3. Generate opaque media IDs rather than persisting arbitrary renderer-readable paths.
4. Validate file type from content, enforce size/dimension limits, and reject SVG/scriptable formats unless sanitized.
5. Clean up replaced profile media without deleting user originals.
6. Use the same media resolver for source covers.
7. Render the configured profile image in the sidebar with a fallback icon.

#### Partial loader resilience

1. Replace broad `Promise.all` calls with:
   - Independent queries where data is unrelated.
   - `Promise.allSettled` plus typed partial results where coordinated refresh is useful.
   - Required/optional dependency groups where one response truly gates another.
2. Preserve the last successful value for each panel.
3. Show a local degraded state and retry on the failing panel.
4. Do not replace an entire page because an optional count, recommendation, health probe, or recent list failed.
5. Bound concurrent refreshes and prevent stale responses from overwriting newer state.

Apply first to:

- Settings health and model/runtime polling.
- App shell jobs, chats, and clusters.
- Chat session and cluster loading.
- Sources and source details.
- Clusters and suggestions.
- Projects and active runs.
- Search result hydration.
- Tasks status/summary.
- Command palette datasets.

#### Shared async primitives

For `useVisiblePolling`:

1. Catch task failures.
2. Support an `onError` callback or return observable error state.
3. Add exponential backoff for repeated failures.
4. Reset backoff after success.
5. Prevent focus and visibility events from producing an immediate retry storm.
6. Ignore results after unmount/cancellation.

For `ConfirmAction`:

1. Await `onConfirm`.
2. Keep the dialog open while pending.
3. Disable duplicate confirmation.
4. Display the rejection in the dialog or through a required caller callback.
5. Close only after confirmed success unless the action explicitly navigates.

#### Health state

1. Give every health request a generation/sequence ID.
2. Abort superseded health calls.
3. Publish `checking` immediately after backend URL or token changes.
4. Ignore responses from an obsolete backend identity.
5. Track core backend, embeddings, model runtime, storage, and maintenance separately.

#### Window chrome

1. Overlay window controls within an existing top header or reserve only the control hit area.
2. Preserve a valid draggable region and keyboard/accessibility behavior.
3. Test maximized, restored, high-DPI, and Windows scaling layouts.

#### Acceptance criteria

- One failed Settings endpoint does not erase healthy cards.
- Polling failures produce no unhandled promise rejections.
- Confirmation failures stay visible beside the confirmation action.
- Profile and source images render under the production CSP.
- The sidebar uses the configured avatar.
- Changing backend identity cannot show health from the previous backend.
- No blank 32-pixel full-width row remains.

### 15.6 Workstream F: Pagination, completeness, and query efficiency

Addresses REL-014 through REL-016.

#### Pagination contract

1. Standardize cursor-based responses:
   - `items`
   - `next_cursor`
   - `has_more`
   - Optional stable total only when inexpensive and semantically valid.
2. Use deterministic ordering with a unique tie-breaker.
3. Support cancellation and bounded page sizes.
4. Migrate chat sessions, chat messages/timelines, clusters, sources, activity, jobs, captures, reviews, and project lists.
5. Keep compatibility adapters only for a bounded migration period.

#### Renderer behavior

1. Use incremental loading or virtualization for large lists.
2. Do not derive global truth from the first page:
   - Saved-chat existence.
   - Sidebar totals.
   - Recent cluster activity.
   - Whether older chat messages exist.
3. Use dedicated summary/count endpoints when the UI needs aggregate state.
4. Display “more results available” rather than silently truncating.

#### N+1 removal

1. Instrument request and SQL query counts for representative routes.
2. Replace per-result HTTP hydration with bulk endpoints or include required summary fields in the search response.
3. Replace per-row SQL lookups with joins, CTEs, grouped queries, or bounded batch fetches.
4. Add indexes only after validating query plans and write amplification.
5. Cache immutable or version-keyed metadata, not permission-sensitive results without vault/client scope in the key.

#### Acceptance criteria

- A vault exceeding every former default limit can reach all records through the UI.
- Sidebar and saved-chat state remain correct beyond the first page.
- Search hydration uses a bounded number of HTTP requests independent of result count.
- Representative backend routes have query-count regression tests.
- Large-list performance targets are measured with 10,000 records.

### 15.7 Workstream G: Odin packaging and product contract

Addresses REL-019 and REL-020.

#### Packaged desktop CLI

1. Decide the supported packaged command form:
   - Installed `odin.exe` shim on a user PATH location, or
   - A documented absolute launcher registered by the desktop, or
   - A copyable PowerShell wrapper installed into an application-owned CLI directory.
2. Install the CLI entry point during packaging; copying `odin_cli.py` alone is insufficient.
3. Keep the CLI version matched to the desktop/backend protocol.
4. Add a first-run UI action that:
   - Installs or repairs the launcher.
   - Shows the resolved command path.
   - Runs `odin --help`.
   - Starts pairing.
5. Update documentation to begin with installation/discovery and `odin auth pair`, not development tokens.
6. Test from a clean PowerShell session without an activated virtual environment or source checkout.

#### Standalone `uv tool` decision

Before publishing `uv tool install odin`, choose and document one contract:

- Thin client: requires a running Vault desktop/backend and only provides remote commands.
- Standalone indexer: owns a separate local database and project lifecycle.
- Embedded local service: installs the required storage/indexing engine and can later pair/synchronize with Vault.

Do not advertise standalone operation until storage ownership, authentication without a desktop runtime descriptor, schema migration, encryption, update compatibility, and synchronization semantics are defined.

If the first release is a thin client:

1. Extract CLI and credential-helper code into a lightweight package.
2. Avoid FastAPI, OCR, model, and full backend dependencies.
3. Discover a running Vault through the protected runtime descriptor.
4. Return a precise “Vault must be running” message.
5. Publish the package under a distinct name if the `odin` package name is unavailable or ambiguous.

#### Acceptance criteria

- `odin --help` and `odin auth pair` work from a clean packaged installation.
- The launcher survives app updates and is removed/repaired predictably.
- Documentation no longer claims unsupported standalone behavior.
- A `uv tool` release, if shipped, installs only its declared lightweight dependencies and passes clean-machine tests.

### 15.8 Workstream H: Test architecture and regression gates

Addresses REL-022 and provides coverage for every workstream.

1. Replace tests that search source text with behavior, component, API-contract, or rendered assertions.
2. Test SSE errors as protocol events rather than expecting an internal Python exception to escape.
3. Add a packaged-runtime dependency probe that imports every required runtime-only dependency.
4. Add a packaged hardware compatibility test that runs with the actual staged interpreter.
5. Add a helper-verification performance test with the real manifest scale.
6. Add startup timing artifacts to CI and compare against an explicit regression budget.
7. Add tests for:
   - Atomic startup status updates.
   - Core-ready versus fully-ready state.
   - Long-operation idempotency and cancellation.
   - Partial loader degradation.
   - Polling and confirmation rejection handling.
   - Pagination past former caps.
   - HTTP and SQL query counts.
   - Image rendering under production CSP.
   - Clean-shell Odin discovery.
8. Keep correctness and performance gates separate so slow infrastructure does not obscure functional failures.
9. Store benchmark baselines by supported hardware class and package version.

## 16. Delivery Sequence

### Phase 0: Baseline and guardrails

- Add startup phase measurement and packaged hardware probes.
- Capture current warm/cold startup distributions.
- Add request, SQL-query-count, and unhandled-rejection instrumentation.
- Convert brittle source-text tests that block safe refactoring.
- Define supported hardware classes and latency budgets.

Exit gate: failures can be reproduced automatically and every later phase has a measurable baseline.

### Phase 1: P0 correctness

- Fix packaged RAM detection and hardware classification.
- Show an immediate startup window.
- Introduce cached, version-bound helper verification.
- Split core readiness from warming.
- Replace the global timeout for known long operations with job submission.

Exit gate: packaged model compatibility works on supported hardware, startup is visibly responsive, and long work cannot falsely appear failed while continuing invisibly.

### Phase 2: P1 reliability

- Correct model discovery roots and persisted folder behavior.
- Implement vector-job prerequisite states.
- Make Settings and route loaders partially resilient.
- Harden polling, confirmations, and health-generation handling.
- Implement secure local image delivery.

Exit gate: expected dependency absence is not reported as failure, partial backend degradation remains usable, and no shared async primitive leaks rejected promises.

### Phase 3: Completeness and scale

- Standardize pagination and migrate consumers.
- Remove semantic-search HTTP N+1 behavior.
- Batch backend SQL access and enforce query budgets.
- Add large-vault and soak coverage.

Exit gate: no list silently truncates product state, and request/query counts remain bounded as result counts grow.

### Phase 4: Product polish and Odin

- Merge desktop chrome into the visible header.
- Localize Settings feedback and correct terminology.
- Ship and document a packaged Odin launcher.
- Decide whether a standalone Odin package is thin-client or self-contained.

Exit gate: clean-machine workflows match all user-facing instructions.

### Phase 5: MCP integration release

Resume the rollout in Section 11 only after Phases 1 and 2 pass. Phase 3 must pass before broad availability. The MCP soak must run on the same startup, timeout, job, pagination, and observability primitives rather than introducing a separate reliability model.

## 17. Ownership and Change Boundaries

Assign one directly responsible owner for each workstream:

| Workstream | Suggested owner boundary |
|---|---|
| A: Startup | Electron main process plus backend lifecycle |
| B: Models | Packaging, hardware detection, and model registry |
| C: Operations | Backend job API plus shared frontend client |
| D: Job prerequisites | Scheduler and embeddings lifecycle |
| E: UI resilience | Desktop shell, Settings, shared async components |
| F: Scale | API pagination, search hydration, and database queries |
| G: Odin | CLI packaging, authentication, and documentation |
| H: Tests | Cross-cutting release engineering |

Cross-boundary changes require an explicit contract first. For example, the frontend must not invent job states that the backend does not persist, and packaging must not silently add a dependency without updating runtime validation and the software bill of materials.

## 18. Consolidated Release Gates

The following gates supplement Section 12:

- A packaged clean-machine probe reports system memory and produces a non-unknown tier on supported hardware.
- Supported Qwen, Phi, Gemma, and Llama GGUF fixtures receive the expected compatibility result.
- The first window is visible before backend `fully_ready`.
- Helper verification cache hits avoid rehashing unchanged 1+ GiB payloads while update/corruption tests still fail closed.
- Normal startup does not run full SQLite integrity checking without a qualifying reason.
- No multi-second or multi-gigabyte operation relies on the generic request timeout.
- No startup vector job fails solely because embeddings are not configured.
- Production CSP permits approved local media through a constrained application mechanism, not arbitrary `file:` access.
- Polling and confirmation failures produce zero unhandled promise rejections.
- Partial endpoint failure does not blank Settings or primary routes.
- All formerly capped collections can be paged to completion.
- Search and representative backend routes pass HTTP/SQL query-count budgets.
- `odin --help` and pairing work from a clean packaged PowerShell session.
- Startup, backend, MCP, and tunnel diagnostics use the same correlation and redaction conventions.
- The full automated suite contains no stale source-text assertions for user-visible behavior.

## 19. Completion Checklist

The remediation program is complete when:

1. Every REL item is linked to an implementation issue or pull request.
2. Each implementation has automated acceptance coverage.
3. Startup and large-vault benchmarks meet the agreed budgets.
4. Clean-machine packaged tests reproduce the supported user workflow.
5. Documentation matches actual model, image, Odin, and MCP behavior.
6. No P0 or P1 item remains open for the broad ChatGPT MCP rollout.
7. Deferred P2 work has an owner, target release, and user-impact rationale.

## 20. Implementation Record and Release Evidence

### 20.1 Status

Implementation of the source-level Vault, desktop, MCP, tunnel, Odin, reliability,
security, and scale work in this plan is complete as of 2026-07-27. No known
source-level P0 or P1 item in the confirmed inventory remains open.

The current Windows installer predates the final MCP transport, feature-flag,
credential, audit, scope-rotation, and setup-flow changes. At the owner's request,
the package rebuild and all post-rebuild packaged-runtime checks are deferred for the
owner to run. Historical package results below remain useful regression evidence but
must not be represented as validation of the latest source.

The release is not yet eligible for broad ChatGPT enablement because the tests that require access to a real ChatGPT workspace and live OpenAI tunnel credentials have not been executed. Those are external validation gates, not missing local implementation. They are listed in Section 20.7 and must not be marked passed without their actual artifacts.

### 20.2 REL implementation matrix

| ID | Status | Implementation and acceptance coverage |
|---|---|---|
| REL-001 | Complete | Packaged runtime includes `psutil`; Windows has a native memory fallback and a distinct detection-failed outcome. Packaged hardware and dependency probes pass. |
| REL-002 | Complete | Electron creates and paints a local startup window before backend readiness. Five-run warm p95 window visibility is 263 ms. |
| REL-003 | Complete | Helper verification is manifest-bound, fail-closed, and cached through a versioned receipt. Cache-hit and invalidation tests cover modified files. |
| REL-004 | Complete | Core readiness is separated from optional warming; normal startup uses lightweight database checks and defers optional work. |
| REL-005 | Complete | The frontend has typed request policies. Model discovery/import, diagnostics, integration work, maintenance, and repair use durable jobs with polling, cancellation, recovery, and idempotency. |
| REL-006 | Complete | Model discovery uses managed, persisted, active-vault, and explicitly approved roots. It no longer recursively scans every drive by default. |
| REL-007 | Complete | GPU inventory participates in classification before eligibility is decided; nominal memory boundaries and CPU/GPU edge cases have regression tests. |
| REL-008 | Complete | Background jobs persist prerequisite/deferred/setup-required states, do not burn retries for missing embeddings, and deduplicate reconciliation. |
| REL-009 | Complete | Local raster media is content-sniffed, size/dimension bounded, copied to app-managed storage, and exposed through opaque traversal-safe IDs under production CSP. |
| REL-010 | Complete | Settings refreshes independent resources with partial-result handling and preserves healthy cards when another endpoint fails. |
| REL-011 | Complete | Visible polling catches failures, backs off, suppresses stale completion, and exposes errors. Confirmations await completion, prevent duplicates, and keep failures visible. |
| REL-012 | Complete | Health requests use generations and cancellation so obsolete backend responses cannot overwrite current state. |
| REL-013 | Complete | Primary loaders were split into required and optional groups with partial degradation for chat, clusters, sources, projects, search, tasks, and shell data. |
| REL-014 | Complete | Cursor contracts and consumers cover chats, timelines, clusters, sources, activity, jobs, captures, reviews, and projects with deterministic tie-breakers. |
| REL-015 | Complete | Dedicated summaries/counts replace first-page-derived global state for chats, activity, and related shell indicators. |
| REL-016 | Complete | Search hydration and representative SQL paths use bounded bulk access. Query-count regressions and 10,000-record tests pass. |
| REL-017 | Complete | Window controls share the application header instead of reserving a blank full-width row; packaged minimum-viewport rendering has no horizontal overflow. |
| REL-018 | Complete | Model action feedback is local to the initiating control, uses simple GGUF terminology, and distinguishes detection failure from incompatibility. |
| REL-019 | Complete | Settings installs or repairs an atomic packaged Odin launcher, updates the user PATH, broadcasts the Windows environment change, and probes `odin --help`. |
| REL-020 | Complete | Odin is explicitly documented and implemented as a thin client to a running Vault desktop. Unsupported standalone indexing is not advertised. |
| REL-021 | Complete | Startup state is atomically replaced and includes instance, sequence, phase, transition, and timing data. Readers retain the last valid state. |
| REL-022 | Complete | Obsolete user-visible source-text assertions were replaced with behavior, API, runtime, rendered UI, packaging, performance, and fault tests. |

### 20.3 MCP and tunnel implementation

- MCP definitions and dispatch are transport-independent in `bridge_mcp_tools.py`;
  bounded newline JSON-RPC transport and concurrent dispatch live in
  `bridge_mcp_stdio.py`; backend tool handlers remain in `bridge_mcp.py`.
- Supported protocol versions are `2025-11-25`, `2025-06-18`, `2025-03-26`, `2024-11-05`, and `2024-10-07`, negotiated from the client request.
- Notifications, request IDs, duplicate in-flight IDs, bounded messages, cancellation, graceful EOF, schemas, annotations, capability profiles, typed results, pagination, safe errors, rate limits, and backpressure are enforced.
- Total serialized tool output is byte-bounded, UTF-8 safe, and explicitly marked
  when shortened. Invalid UTF-8, unsafe Unicode controls, surrogate code points,
  malformed JSON, oversized lines, and backend connection resets fail safely.
- Read/write operations use backend authorization and idempotency rather than relying on hidden UI controls.
- Every recognized client write attempt is audited before authorization; completed
  mutations are recorded separately. Read-only, out-of-scope, stale, conflicting,
  replayed, and successful attempts have regression coverage.
- The packaged MCP child receives a minimal environment and never receives the desktop backend bearer token.
- The MCP child accepts only a plain HTTP loopback backend origin. Manifest verification
  rejects symlinked helper payloads even when the target hash matches.
- Tunnel identity and Bridge client identity remain separate. Credentials are stored with Electron safe storage; persisted descriptors contain identity but not plaintext credentials.
- Credential replacement is atomic and fail-closed on unavailable OS encryption,
  disk-full errors, newer credential schemas, and incompatible launcher versions.
- Tunnel supervision covers loopback readiness, exponential jittered reconnect, permanent failure, rapid disconnect, crash, stale-owner reconciliation, and orphan cleanup.
- Disconnect-and-revoke removes the tunnel credentials and the associated Bridge client rather than leaving a valid local client behind.
- Permission-sensitive client edits rotate the scoped token automatically and refresh
  an active tunnel with the new token. Active-vault deletion forgets the tunnel before
  tombstoning local vault data.
- The ChatGPT desktop flow is numbered and resumable from durable client, scope,
  tunnel, and request-audit state. It detects a successful `list_clusters` check,
  explains the confirmed-write test, and keeps eligibility copy conditional.
- Explicit source and Electron rollout flags cover setup, tunnel, write tools,
  streaming, and future remote HTTP; disabled write capability downgrades to read-only.
- The pinned packaged tunnel is `0.0.10+105e17a79a36e4e5c897fd698ed2b8dbf935b144`; the staged archive and binary are checksum verified.
- Compatibility baseline: Vault desktop `0.1.9`, tunnel client `0.0.10`, and the MCP versions listed above.

### 20.4 Product and packaging implementation

- The most recent historical Windows artifacts are `win-unpacked` and
  `test-0.1.9-Setup.exe` (692,097,270 bytes). They predate the final 2026-07-27
  source changes and are not release candidates for this source tree.
- The package contains the backend, Python runtime, Torch 2.13.0, SentenceTransformers 5.5.1, Transformers 5.6.0, OCR tools, browser runtime, local LLM runtime, tunnel client, helper manifest, and model integrity manifest.
- Installed-app probes use isolated user data and separate installer/startup timeouts. They remove the current-user installation afterward and reject residual packaged files.
- The aggregate clean-machine validator now exits nonzero whenever its JSON report has `pass: false`; a failed subgate can no longer be hidden by a successful script exit.
- Odin works in a clean PowerShell environment without host Python, host Node, an activated virtual environment, or a source checkout.
- Documentation in `WORKING_COMMANDS.md` and `ARCHITECTURE.md` matches the packaged thin-client and tunnel behavior.

### 20.5 Executed evidence

| Gate | Result |
|---|---|
| Full backend suite, latest source | 810 passed, 1 optional skip, 2 scale tests deselected, 0 failed; 286.55 s. An audit-sentinel regression was found by the first run, fixed, and covered before this clean rerun. |
| Electron and TypeScript, latest source | 91/91 Electron tests passed; `tsc --noEmit` passed. |
| Interactive control audit | Passed across 42 TSX files. |
| Backend dependency audit | `pip-audit --local`: no known vulnerabilities. |
| Packaged dependency audit | Packaged `site-packages`: no known vulnerabilities. |
| Production npm audit | 0 production vulnerabilities. |
| Security end-to-end, latest source | Clean vault, interruption, offline-at-rest, and 1,200-source encrypted-vault gates passed. The latest large run imported 1,200/1,200 with 0 failures; scan 0.15 s, refresh 42.62 s, reindex 592.82 s, query 195.14 ms. Offline marker hits: 0. |
| Packaged runtime, historical artifact | Previously passed auth, CORS, backend, model setup/runtime, embedding, image OCR, PDF OCR, Tesseract, Ghostscript, and qpdf. Must be rerun after the owner rebuilds. |
| Packaged full vault, historical artifact | Previously passed semantic retrieval, generated OCR fixtures, durable diagnostic artifact, and startup registration. Must be rerun after rebuild. |
| Dynamic-link isolation, historical artifact | Previously passed against `example.com`; must be rerun after rebuild. |
| Migration drill, historical artifact | Previously passed, including interrupted migration entering a safe degraded state. |
| MCP Inspector, latest source | Development stdio read-only and read/write profiles passed with Inspector 0.21.2. The older packaged profiles also passed but are stale for the latest source. |
| MCP source soak, latest source | 1,000 calls passed; initialization 824.159 ms, tool listing 1.552 ms, `list_clusters` p95 86.93 ms, maximum 160.779 ms, MCP RSS growth 0 MiB. The isolated rate bucket was reset every 50 successes to measure sustained handler behavior. |
| MCP packaged soak, historical artifact | Previously passed 1,000 calls; initialization 388.407 ms, `list_clusters` p95 40.669 ms, maximum 72.42 ms, MCP RSS growth 2.898 MiB. Must be rerun after rebuild. |
| Tunnel lifecycle faults | Healthy readiness, prompt crash failure, reconnect backoff, stale-owner cleanup, and rapid disconnect cancellation passed. |
| Startup performance | Five warm packaged runs passed: window-visible p95 263 ms, backend-ready p95 2,665.48 ms, renderer-ready p95 3,018.72 ms. |
| Rendered packaged UI | Real Electron at 1024×680 passed with zero console errors, zero horizontal overflow, and a visually inspected onboarding screenshot. |
| Clean-shell Odin | Passed without host Python or Node; `odin --help` succeeded and offline pairing returned the actionable exit code 3. |
| Real public Git repositories | Odin add/status/sync/tree/graph/context passed against immutable commits from `pallets/itsdangerous` and `sindresorhus/yoctocolors`; before/after Git tree hashes were unchanged. |
| Odin scale, latest source | 50,000-file discovery passed in 160.824 s with 68.3 MiB peak memory while Inspector ran concurrently. The prior isolated run was 95.777 s. |
| Product scale, latest source | 10,000-source metadata query passed in 0.108 s. |
| Installed artifact, historical | The older isolated current-user install reached pre-vault backend and renderer ready, then uninstalled without host runtimes. Must be rerun after rebuild. |
| Installer lifecycle, historical | The older installer created its uninstall entry and both shortcuts, then uninstalled under the documented app-data preservation policy. Must be rerun after rebuild. |
| Package layout | 503 manifest entries; no writable/helper overlaps. |
| Diff hygiene | `git diff --check` passed; only repository line-ending conversion warnings were emitted. |

Primary machine-readable artifacts are under `tmp/`, including:

- `security-e2e-final-2/security-e2e-summary.json`
- `mcp-soak-packaged-1000.json`
- `packaged-startup-benchmark-final.json`
- `packaged-ui-smoke-final.json` and `packaged-ui-smoke-final.png`
- `pip-audit-final.json` and `pip-audit-packaged-final.json`
- `odin-launcher-package-final.json`
- `odin-public-smoke-20260727-172747/odin-public-repos-report.json`
- `installed-app-smoke-final.json`
- `installer-lifecycle-final.json`
- `clean-machine-package-validation-final.json`
- `local-validation-20260727/security-clean.json`
- `local-validation-20260727/security-offline.json`
- `local-validation-20260727/security-interrupted.json`
- `local-validation-20260727/security-large-1200.json`
- `local-validation-20260727/mcp-soak-source-1000.json`

### 20.6 Owner-deferred package rebuild

The owner will rebuild the Windows package. After that rebuild, the following local
gates must be rerun against the new artifact:

1. Packaged read-only and read/write Inspector profiles.
2. Packaged 1,000-call soak and overload checks.
3. Packaged runtime, full-vault, OCR, migration, and dynamic-link isolation smokes.
4. Startup benchmark and rendered Electron UI checks.
5. Clean-shell Odin launcher and public-repository smoke.
6. Package-layout/helper-manifest validation.
7. Isolated install, shortcut/registry, launch, uninstall, and residual-file checks.

### 20.7 External release gates still required

These checks need an authorized real ChatGPT workspace and live OpenAI tunnel credentials. They were not available in this implementation environment and are therefore pending:

1. Create a real tunnel identity and connect the final packaged Vault build.
2. Run the ChatGPT tool scan for both read-only and read/write profiles.
3. Ask ChatGPT in natural language to list clusters, retrieve grounded context, and expand one context item.
4. Exercise approved writeback, duplicate/idempotent retry, and denied-write behavior.
5. Revoke once from Vault and once from ChatGPT, confirming immediate denial and local cleanup in both directions.
6. Run a real credentialed 24-hour idle/reconnect soak and check memory, handles, processes, and bounded logs.
7. Capture workspace surface, account eligibility, tunnel, tool-scan, call, revoke, and soak artifacts in the release record.

Broad rollout remains disabled until the owner-deferred package gates and all seven
external checks pass. The latest source soak and tunnel fault suite reduce risk but do
not substitute for a rebuilt artifact or credentialed ChatGPT validation.
