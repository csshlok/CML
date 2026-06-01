# Testing Cases 2026-06-01

Source: `T:\csshl\CML_TESTING_PARAMETERS.md`

## Automated This Pass

- `Pre-vault mode guard`
  Expected: private vault/chat/search/bridge routes return `409`, health and system preflight stay available.
  Result: `PASS`
  Coverage: [backend/tests/test_parameters_doc_cases.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_parameters_doc_cases.py:34)

- `Reserved complete_analysis field`
  Expected: valid JSON request with `complete_analysis` returns `501`; malformed JSON still returns a normal parse/validation error instead of `501`.
  Result: `PASS`
  Coverage: [backend/tests/test_parameters_doc_cases.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_parameters_doc_cases.py:65)

- `Synthesis gating for recent retriable generations`
  Expected: jobs with `can_run_during_synthesis = false` stay blocked while a recent `retriable` generation exists, but can be claimed once the generation is outside the policy window.
  Result: `PASS`
  Coverage: [backend/tests/test_parameters_doc_cases.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_parameters_doc_cases.py:83)

- `Bridge raw-text redaction`
  Expected: when `allow_raw_snippets = false`, Bridge context returns source metadata without raw/extracted body text.
  Result: `PASS`
  Coverage: [backend/tests/test_parameters_doc_cases.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_parameters_doc_cases.py:129)

- `Existing backend regression suite`
  Scope: jobs, Bridge/MCP basics, ingestion, OCR fallback, retrieval snapshots, deletion, diagnostics redaction, generation recovery, embeddings, extension capture, expert scaffold, vault lock audit.
  Result: `PASS`
  Coverage: [backend/tests/test_background_jobs.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_background_jobs.py:1), [backend/tests/test_bridge_mcp.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_bridge_mcp.py:1), [backend/tests/test_source_pages.py](/c:/Users/csshl/Desktop/CML/backend/tests/test_source_pages.py:1)

## Reproduced Failure

- `Cross-vault cluster assignment`
  Expected: creating or updating a source in vault A with a cluster from vault B should be rejected.
  Actual: the backend accepts it because the source route checks only cluster existence, not `cluster.vault_id`.
  Result: `FAIL`
  Relevant code: [backend/app/api/routes/sources.py](/c:/Users/csshl/Desktop/CML/backend/app/api/routes/sources.py:66), [backend/app/api/routes/sources.py](/c:/Users/csshl/Desktop/CML/backend/app/api/routes/sources.py:272)

## Not Exercised In This Pass

- Packaged Electron flows: second-instance handling, backend URL handoff, token handoff, vault picker path correctness.
- Windows process/PID lock edge cases: reassigned PID, CIM denial, override audit completeness.
- Corrupt SQLite startup halt and repair UI.
- Large-file / large-vault performance, disk-full, model download cancellation, packaged cold-start timing.
- Real network/browser ingestion cases that need external fixtures or Playwright runtime.
