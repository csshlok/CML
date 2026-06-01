# Test Execution Report 2026-06-01

Inputs reviewed:
- `T:\csshl\CML_TESTING_PARAMETERS.md`
- [backend/tests/CML_400_TEST_CASES.md](/c:/Users/csshl/Desktop/CML/backend/tests/CML_400_TEST_CASES.md:1)
- [docs/QA_MASTER_TEST_CATALOG_2026-06-01.md](/c:/Users/csshl/Desktop/CML/docs/QA_MASTER_TEST_CATALOG_2026-06-01.md:1)

## Automated suites run

```powershell
.venv\Scripts\python -m unittest discover -s backend\tests -v
node --test apps\desktop\electron\token-store.test.cjs apps\desktop\electron\main.behavior.test.cjs
npm run build --workspace @cml/desktop
npm run package:win --workspace @cml/desktop
npm audit --workspace @cml/desktop --json
npm audit --omit=dev --workspace @cml/desktop --json
.venv\Scripts\python -m pip_audit
```

Results:
- Backend `unittest`: `115` tests executed, `97` passing, `17` expected failures, `1` skipped, `0` unexpected failures.
- Electron shell tests: `10/10` passing.
- Desktop production build: passed.
- Windows package build: passed. Artifacts written to [apps/desktop/release](/c:/Users/csshl/Desktop/CML/apps/desktop/release:1), including [CML-0.1.0-Setup.exe](/c:/Users/csshl/Desktop/CML/apps/desktop/release/CML-0.1.0-Setup.exe:1).
- `npm audit` for `@cml/desktop`: `0` vulnerabilities, both full tree and `--omit=dev`.
- `pip_audit` in the checked-in backend venv: `0` known vulnerabilities. One local package (`cml-backend`) was skipped because it is not published on PyPI.

## Automated coverage added in this pass

- [backend/tests/test_parameters_doc_cases.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_parameters_doc_cases.py:1)
- [backend/tests/test_additional_qa_cases.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_additional_qa_cases.py:1)
- [backend/tests/test_system_vault_lock_and_embeddings.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_system_vault_lock_and_embeddings.py:1)
- [apps/desktop/electron/token-store.test.cjs](/c:/Users/csshl/Desktop/CML/apps/desktop/electron/token-store.test.cjs:1)
- [apps/desktop/electron/main.behavior.test.cjs](/c:/Users/csshl/Desktop/CML/apps/desktop/electron/main.behavior.test.cjs:1)

## Coverage snapshot

- Executed checks now include `115` backend tests, `10` Electron shell tests, dependency audits, package/build verification, and multiple heavy runtime probes.
- The executable coverage already spans well over `200` parameter rows from the source documents because many tests assert more than one parameterized expectation at once, but the run is still incomplete for the OS-level and interactive gaps listed below.

## Confirmed passing areas

- Pre-vault route gating and availability of health/preflight endpoints.
- Reserved `complete_analysis` rejection behavior.
- Scheduler priority, dependency cancellation, requeue recovery, same-scope blocking, synthesis gating.
- Bridge token requirement, disable behavior, rotation invalidation, redaction, independent client permissions.
- MCP notification behavior and backend-unreachable / cluster-not-allowed / no-active-vault mappings.
- Immediate search exclusion on source delete and retrieval snapshot deletion-state updates.
- Transcript source cleanup when deleting a chat session.
- Vector reconciliation for missing and stale chunks.
- OCR fallback preference logic and OCR runtime status shape.
- Diagnostic bundle creation and raw-secret redaction.
- Local API auth inactive when no token is configured; bearer auth works when token is configured.
- Startup phase fallback when shared phase file cannot be read.
- Integration folder scan without vault does not persist import history.
- Token-store roundtrip, short-token rejection, and stable `getOrCreateToken`.
- URL ingestion resolves relative `og:image` links to absolute URLs and rejects oversized HTML responses.
- Redirect SSRF guard blocks loopback redirect targets during URL ingestion.
- URL 404 ingestion returns a clean client error instead of surfacing an internal server failure.
- Text ingestion stores SQL-looking payloads literally.
- Assistant-message `useful` flag persists and reloads correctly.
- Streaming endpoint emits `meta -> token -> done` in the normal path.
- Vault-lock acquire/reclaim/conflict/override/release behaviors are exercised directly.
- Live Windows owner classification correctly recognizes a real `uvicorn backend.app.main:app` backend process as `vault_backend`.
- Pre-vault startup-status and embedding-configure routes remain available.
- Hash embedding configuration is rejected when the dev flag is off.
- Embedding-download cancel path marks the state as cancelled.
- Local model cancellation removes the partial `.part` file and leaves the model in `cancelled` rather than a half-installed state.
- Local model status ignores non-`.gguf` files and only reports `installed` when a matching GGUF is present.
- Startup-status fallback still returns a known phase when the shared phase file is unreadable.
- Startup migration recovery detects interrupted `running` migration records.
- Electron second-instance logic focuses the existing window and shows the already-open dialog when a second vault is requested.
- Electron second-instance logic without a vault arg focuses the existing window without surfacing a false conflict dialog.
- Electron external URL guard allows `http/https/mailto` and blocks `file:`, `ftp:`, and `javascript:`.
- Electron vault-path persistence handles unicode and spaces and creates the `.vault` directory under the selected path.
- Electron recursive source-file collection skips symlinks and skipped build folders such as `node_modules`.
- Electron port selection skips an occupied loopback port and chooses the next free candidate in the packaged backend range.
- Desktop dependency audits did not surface known package CVEs in the currently installed trees.

## Heavy probes run

- `Corrupt database startup probe`
  Result: backend halted with `startup_failed` and message `database disk image is malformed`. This is a real stop, but it does not currently normalize to the spec's expected `integrity_check_failed` phase.

- `Scale probe: 1,000 indexed sources across 20 clusters`
  Result: `1000` sources created in `7.081s`, indexed in `0.726s`, semantic search in `0.0831s`.
  Caveat: the top semantic hit for query `unique topic 777 scale probe evidence` returned `Source 597`, which suggests ranking quality issues under hash embeddings even though latency stayed low.

- `Upload stress probe: 200 local text files through from-path ingestion`
  Result: `200` files ingested in `11.061s`, indexed in `0.415s`, producing `400` chunks.

- `Embedding runtime bring-up probe`
  Result: `embedding_status()` reported a real SentenceTransformers runtime as available from local cache (`T:\LLM\embeddings`), but `start_embedding_model_download()` ended in `failed` with `Cannot send a request, as the client has been closed.` in this environment.

- `Packaged win-unpacked process probe`
  Result: [apps/desktop/release/win-unpacked/CML.exe](/c:/Users/csshl/Desktop/CML/apps/desktop/release/win-unpacked/CML.exe:1) exited with code `0` within `8s` under an isolated fresh profile and did not create `startup-status.json` or `active-vault.json`.

- `Packaged second-instance process probe`
  Result: the second packaged process exited immediately under the same isolated profile, but the first process also did not remain running long enough to prove real single-instance window behavior. This is partial evidence only.

- `Dependency audit probe`
  Result: `npm audit` returned zero vulnerabilities for the desktop workspace in both full-tree and `--omit=dev` modes. `pip_audit` returned zero known vulnerabilities for the Python environment, with only the local unpublished `cml-backend` package skipped from PyPI lookup.

- `Real C: disk preflight probe`
  Result: the machine currently has about `4.74 GB` free on `C:`. `POST /api/v1/system/preflight/disk` returned `ok = false` for a `6 GB` requirement and `ok = true` for a `500 MB` requirement, so the generic disk preflight route is behaving correctly against the actual low-space system state.

- `Packaged alternate-port probe with occupied backend range`
  Result: before launch, listeners already existed on `127.0.0.1:7343` and `127.0.0.1:7344`. Launching [apps/desktop/release/win-unpacked/CML.exe](/c:/Users/csshl/Desktop/CML/apps/desktop/release/win-unpacked/CML.exe:1) under an isolated profile produced no new listeners in `7343-7355`, created no `startup-status.json`, created no `active-vault.json`, and exited with code `0`. This is stronger evidence that the packaged app is failing before it can hand off a usable backend URL or persist startup state.

- `Packaged isolated-profile artifact probe`
  Result: after the packaged app exited under a fresh isolated profile, the only created profile tree was `Microsoft\Windows\Caches`. No Vault-owned profile files were written before exit, which suggests the failure happens before normal user-data initialization and before startup-status persistence.

- `Large-model preflight bypass probe`
  Result: with the registry forced to treat `gemma-3-12b-it-q4_k_m` as not installed, the machine had about `5.09 GB` free on `C:` against an estimated `7.41 GB` requirement, but `start_model_download()` still returned `status = resolving` instead of refusing the download up front.

- `Late download-cancel race probe`
  Result: if cancellation lands after a fast local-model download has already completed, `cancel_model_download()` can still overwrite the registry state to `cancelled` even though the final `.gguf` file remains on disk. The mid-download cancellation path still cleaned up correctly, so this is specifically a post-completion state race.

- `Packaged backend-runtime isolation probe`
  Result: launching [resources/python-runtime/Scripts/python.exe](/c:/Users/csshl/Desktop/CML/apps/desktop/release/win-unpacked/resources/python-runtime/Scripts/python.exe:1) directly from [apps/desktop/release/win-unpacked/resources](/c:/Users/csshl/Desktop/CML/apps/desktop/release/win-unpacked/resources:1) with `-m uvicorn backend.app.main:app --host 127.0.0.1 --port 7355` served `/health = {"status":"ok","service":"cml-backend"}` successfully. That means the packaged Python runtime and bundled backend code can run in isolation; the packaged-app early exit is more likely in the Electron bootstrap, backend spawn handoff, or renderer startup path.

- `Packaged process-tree probe`
  Result: launching [apps/desktop/release/win-unpacked/CML.exe](/c:/Users/csshl/Desktop/CML/apps/desktop/release/win-unpacked/CML.exe:1) under a fresh isolated profile and inspecting `Win32_Process` children after `5s` showed `exit_code = 0` and `children = []`. So the packaged app is exiting before it leaves any observable backend or renderer child process behind.

- `Packaged clean-launch probe after removing dev-instance lock holder`
  Result: after terminating the live workspace dev Electron/backend processes that could have held the app's single-instance lock, launching [apps/desktop/release/win-unpacked/CML.exe](/c:/Users/csshl/Desktop/CML/apps/desktop/release/win-unpacked/CML.exe:1) under a fresh isolated profile still exited `0` within `10s`, with `children = []`, no loopback listeners, no `startup-status.json`, and no `active-vault.json`. So the early packaged exit is not just a false positive caused by an already-running dev instance.

- `Packaged renderer bootstrap isolation probe`
  Result: calling `startPackagedRendererServer()` directly from the packaged [electron/main.cjs](/c:/Users/csshl/Desktop/CML/apps/desktop/electron/main.cjs:1) code with the real packaged `dist/client` and `dist/server` assets succeeded and returned `http://127.0.0.1:5174/`.

- `Packaged ensureBackend isolation probe`
  Result: calling `ensureBackend()` directly from the packaged [electron/main.cjs](/c:/Users/csshl/Desktop/CML/apps/desktop/electron/main.cjs:1) code with `process.resourcesPath` pointed at [apps/desktop/release/win-unpacked/resources](/c:/Users/csshl/Desktop/CML/apps/desktop/release/win-unpacked/resources:1) succeeded and returned `http://127.0.0.1:7343`.

- `Windows vault-lock owner classification probes`
  Result: a real `python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 7355` process classified correctly as `vault_backend`, but an unrelated sleeper launched as `python -c "import time; time.sleep(15)" backend.app.main` also classified as `vault_backend` purely because the argv contained the token `backend.app.main`.

## Confirmed defects

The following are real failures, tracked in the suite as expected failures or reproduced probes:

1. `Cross-vault cluster assignment accepted`
   Evidence: expected-failure test in [test_additional_qa_cases.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_additional_qa_cases.py:366)
   Relevant code: [backend/app/api/routes/sources.py](/c:/Users/csshl/Desktop/CML/backend/app/api/routes/sources.py:66), [backend/app/api/routes/sources.py](/c:/Users/csshl/Desktop/CML/backend/app/api/routes/sources.py:272)

2. `Retriable generation breaks combined timeline`
   Evidence: expected-failure test in [test_additional_qa_cases.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_additional_qa_cases.py:271)
   Relevant code: [backend/app/api/routes/chat.py](/c:/Users/csshl/Desktop/CML/backend/app/api/routes/chat.py:140)

3. `Packaged loopback renderer origin is not CORS-allowlisted`
   Evidence: expected-failure test in [test_additional_qa_cases.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_additional_qa_cases.py:396)
   Relevant code: [backend/app/main.py](/c:/Users/csshl/Desktop/CML/backend/app/main.py:28)

4. `Windows-1252 text decoding is lossy`
   Evidence: expected-failure test in [test_additional_qa_cases.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_additional_qa_cases.py:411)
   Relevant code: [backend/app/core/extraction.py](/c:/Users/csshl/Desktop/CML/backend/app/core/extraction.py:89)

5. `Backend token stored as plaintext on disk`
   Evidence: expected-failure test in [test_additional_qa_cases.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_additional_qa_cases.py:422)
   Relevant code: [apps/desktop/electron/token-store.cjs](/c:/Users/csshl/Desktop/CML/apps/desktop/electron/token-store.cjs:1)

6. `Bridge/MCP error-code registry does not match spec for vault_not_found`
   Evidence: expected-failure test in [test_additional_qa_cases.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_additional_qa_cases.py:428)
   Relevant code: [backend/app/bridge_mcp.py](/c:/Users/csshl/Desktop/CML/backend/app/bridge_mcp.py:151)

7. `Deleting a chat session leaves attachment-created source records behind`
   Evidence: expected-failure test in [test_additional_qa_cases.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_additional_qa_cases.py:433)
   Relevant code: [backend/app/api/routes/chat.py](/c:/Users/csshl/Desktop/CML/backend/app/api/routes/chat.py:159), [backend/app/api/routes/chat.py](/c:/Users/csshl/Desktop/CML/backend/app/api/routes/chat.py:1032)

8. `Saving an assistant message does not propagate the session saved flag`
   Evidence: expected-failure test in [test_additional_qa_cases.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_additional_qa_cases.py:341)
   Relevant code: [backend/app/api/routes/chat.py](/c:/Users/csshl/Desktop/CML/backend/app/api/routes/chat.py:199)

9. `Whitespace-only pasted text is accepted instead of being rejected or marked no-content`
   Evidence: expected-failure test in [test_additional_qa_cases.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_additional_qa_cases.py:367)
   Relevant code: [backend/app/api/routes/sources.py](/c:/Users/csshl/Desktop/CML/backend/app/api/routes/sources.py:179), [backend/app/api/routes/sources.py](/c:/Users/csshl/Desktop/CML/backend/app/api/routes/sources.py:48)

10. `Persisted chat failures leave orphaned in-flight generations`
   Evidence: expected-failure test in [test_additional_qa_cases.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_additional_qa_cases.py:545)
   Relevant code: [backend/app/api/routes/chat.py](/c:/Users/csshl/Desktop/CML/backend/app/api/routes/chat.py:209), [backend/app/api/routes/chat.py](/c:/Users/csshl/Desktop/CML/backend/app/api/routes/chat.py:828)

11. `Vault-lock audit route is still reachable in pre-vault mode`
   Evidence: expected-failure test in [test_system_vault_lock_and_embeddings.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_system_vault_lock_and_embeddings.py:1)
   Relevant code: [backend/app/api/routes/system.py](/c:/Users/csshl/Desktop/CML/backend/app/api/routes/system.py:71)

12. `Corrupt database startup is not classified as integrity_check_failed`
   Evidence: corrupt-startup probe returned `startup_failed` with `DatabaseError` instead of the documented integrity phase.
   Relevant code: [backend/app/main.py](/c:/Users/csshl/Desktop/CML/backend/app/main.py:38), [backend/app/core/startup_checks.py](/c:/Users/csshl/Desktop/CML/backend/app/core/startup_checks.py:8)

13. `Embedding download/install path is unreliable in this environment`
   Evidence: real download probe failed with `Cannot send a request, as the client has been closed.` while runtime detection still found an already-available local model cache.
   Relevant code: [backend/app/core/embeddings.py](/c:/Users/csshl/Desktop/CML/backend/app/core/embeddings.py:77)

14. `Packaged win-unpacked app does not stay alive under a fresh isolated profile`
   Evidence: process-level probes showed `CML.exe` exiting with code `0` within `8-10s` without creating user-data startup artifacts, with no observable child processes after launch, and the same behavior persisted even after terminating the workspace dev Electron/backend processes that could have held the single-instance lock. The packaged Python runtime, packaged renderer server bootstrap, and packaged `ensureBackend()` path all succeed when invoked directly from the packaged assets, so the remaining fault surface is narrowed to the actual Electron app lifecycle / window startup path.
   Relevant code: [apps/desktop/electron/main.cjs](/c:/Users/csshl/Desktop/CML/apps/desktop/electron/main.cjs:1)

15. `Full startup phase sequence does not match the testing spec`
   Evidence: expected-failure test in [test_system_vault_lock_and_embeddings.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_system_vault_lock_and_embeddings.py:1) shows the recorded phases do not include the spec's expected `vault_lock_acquired` milestone and do not preserve the documented ordering.
   Relevant code: [backend/app/main.py](/c:/Users/csshl/Desktop/CML/backend/app/main.py:38), [backend/app/core/startup_state.py](/c:/Users/csshl/Desktop/CML/backend/app/core/startup_state.py:1)

16. `Vault-lock override audit trail is incomplete versus the testing spec`
   Evidence: expected-failure test in [test_system_vault_lock_and_embeddings.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_system_vault_lock_and_embeddings.py:1) shows the audit log records acquisition events but not the full detection/dialog/user-choice/startup-result sequence required by the spec.
   Relevant code: [backend/app/core/vault_lock.py](/c:/Users/csshl/Desktop/CML/backend/app/core/vault_lock.py:1), [backend/app/api/routes/system.py](/c:/Users/csshl/Desktop/CML/backend/app/api/routes/system.py:71)

17. `Null bytes in pasted text are accepted and stored inconsistently`
   Evidence: expected-failure test in [test_additional_qa_cases.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_additional_qa_cases.py:1) and a direct probe showed `abc\x00def` is accepted; SQLite then reports a truncated logical length while the raw value still contains the null byte.
   Relevant code: [backend/app/api/routes/sources.py](/c:/Users/csshl/Desktop/CML/backend/app/api/routes/sources.py:179), [backend/app/schemas.py](/c:/Users/csshl/Desktop/CML/backend/app/schemas.py:88)

18. `Large local-model downloads do not enforce disk preflight before starting`
   Evidence: the large-model probe on this machine showed `gemma-3-12b-it-q4_k_m` begins with `status = resolving` even when the real free space on `C:` is below the model's estimated download size, and there is now an expected-failure automated test covering the same behavior in [test_system_vault_lock_and_embeddings.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_system_vault_lock_and_embeddings.py:1).
   Relevant code: [backend/app/core/model_registry.py](/c:/Users/csshl/Desktop/CML/backend/app/core/model_registry.py:116), [backend/app/core/preflight.py](/c:/Users/csshl/Desktop/CML/backend/app/core/preflight.py:1)

19. `Late download cancellation can mislabel an installed local model as cancelled`
   Evidence: a real on-disk probe and an expected-failure automated test in [test_system_vault_lock_and_embeddings.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_system_vault_lock_and_embeddings.py:1) show `cancel_model_download()` can flip state to `cancelled` after the final GGUF already exists.
   Relevant code: [backend/app/core/model_registry.py](/c:/Users/csshl/Desktop/CML/backend/app/core/model_registry.py:143), [backend/app/core/model_registry.py](/c:/Users/csshl/Desktop/CML/backend/app/core/model_registry.py:180)

20. `Vault-lock PID verification can misclassify an unrelated live process as a real backend`
   Evidence: a live Windows probe and an expected-failure automated test in [test_system_vault_lock_and_embeddings.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_system_vault_lock_and_embeddings.py:1) showed `python -c "import time; time.sleep(15)" backend.app.main` classifies as `vault_backend`, even though it is not serving the app and only carries `backend.app.main` as an argv token. This weakens the intended PID-reuse protection from the testing spec.
   Relevant code: [backend/app/core/vault_lock.py](/c:/Users/csshl/Desktop/CML/backend/app/core/vault_lock.py:123)

## Manual / packaged / external-state cases not fully executed yet

- Restricted-account Windows verification failures for PID inspection.
- Full interactive Electron repair UI validation beyond the main-process phase messaging already exercised.
- Disk-full simulation for vector writes and download/install flows.
- Real packaged-app second-instance behavior at the OS window/process level, beyond the main-process handler tests.
- Real model download cancellation with partial-file cleanup verification on disk.
- End-to-end proof that a packaged app can survive an occupied `7343` and successfully bind a later port in the `7343-7355` range. The current evidence only proves early packaged failure.
- End-to-end streaming disconnect/retry UX from the renderer, beyond the backend event-sequence and orphan-generation probes.
- External authenticated-page fixtures and very large real-world HTML fixtures.

## Current interpretation

Executable local coverage is substantially broader now: backend automation, Electron shell behavior, dependency audits, packaged build creation, startup-failure probing, upload stress, and scale measurements have all been exercised. The objective is still not complete because several OS-level and externally dependent cases from the source documents remain unverified.
