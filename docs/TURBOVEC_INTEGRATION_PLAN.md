# Turbovec Integration And Benchmark Plan

Last updated: 2026-06-14

## Current Status

This plan is no longer a pure forward-looking proposal.

Current repo state:

- Phase A is implemented.
- Phase B is implemented.
- Phase C runtime wiring is implemented in product code.
- `vector_search_backend=auto` now gates turbovec usage on:
  - chunk-count threshold
  - sidecar health
  - Phase C benchmark approval for the active tuple

The remaining work is no longer “add Phase C architecture.” It is:

- gather broader natural-corpus benchmark evidence
- validate default-policy confidence on real vaults
- keep fallback/repair behavior honest in release proof and operator wording

Primary implementation points:

- `backend/app/core/turbovec_runtime.py`
- `backend/app/core/turbovec_benchmark.py`
- `backend/app/api/routes/search.py`
- `backend/tests/test_turbovec_runtime.py`
- `backend/tests/test_turbovec_benchmark.py`

## Objective

Keep SQLite authoritative while using turbovec as a derived vector sidecar that can accelerate large-vault semantic retrieval without weakening tuple isolation, repair, or fallback behavior.

## Current CML Retrieval Architecture

Today the repo supports three runtime modes:

- `exact`
- explicit `turbovec`
- `auto`

The backend still treats SQLite as the source of truth for:

- chunk text
- trust metadata
- deleted-state filtering
- active embedding tuple
- repair and reconciliation

Turbovec is used only as the vector-search sidecar over already eligible chunk ids.

## Confirmed Design Decisions Still In Force

These decisions remain aligned with the code:

1. Sidecar identity key is `vault_id + derived_state_epoch`.
2. Sidecar manifest stores the full tuple for diagnostics.
3. `.tvim` is not encrypted at rest in the current phase.
4. `.tvim` lives only under the vault-controlled derived-artifact area.
5. Sidecars are treated as sensitive derived state.
6. Sidecar failure must fail closed to exact fallback or repair.
7. Incremental patching is allowed with rebuild thresholds.
8. Mid-query sidecar failure marks the manifest unhealthy before exact fallback.
9. Auto mode is gated by threshold plus Phase C approval, not just by sidecar existence.

## Phase Status

### Phase A: Benchmark And Backend Abstraction

Status: complete.

Completed:

- vector-backend abstraction exists
- current exact backend remains available
- turbovec benchmark helpers exist
- benchmark outputs and overlap math exist

### Phase B: Derived Sidecar Integration

Status: complete.

Completed:

- sidecar build/status/repair flows
- manifest schema and validation
- incremental add/remove updates
- source-delete propagation
- startup repair integration
- fail-closed fallback behavior

### Phase C: Default Query Path

Status: implemented in product code, still awaiting broader evidence for rollout confidence.

Completed:

- SQL eligibility filter still runs first
- turbovec searches only the eligible id set
- SQLite hydrates final rows/snippets/metadata
- per-vault Phase C benchmark endpoint exists
- approval is persisted against the active tuple
- `auto` mode only uses turbovec when:
  - sidecar is healthy
  - eligible chunk count meets the threshold
  - Phase C benchmark approval exists for the active tuple

Current threshold:

- `turbovec_min_chunk_count = 10000`

## Current Acceptance Reality

What is implemented:

- Phase C benchmark API and persistence
- auto-backend gate
- published-sidecar search path
- exact fallback path
- corrupt-manifest and unhealthy-sidecar handling

What remains open:

- larger natural-corpus benchmark evidence
- clearer operator/user wording around when auto mode is considered trustworthy enough for release positioning
- more real user-owned corpus evidence beyond the current capped and synthetic runs

## Benchmark Evidence Now On Record

The repo and context docs now record benchmark evidence beyond the original 8-PDF prototype phase, including:

- early real-PDF and replicated prototype comparisons
- 1500-source retrieval benchmark proof
- broader user-owned repo-root benchmark passes
- exact-search scaling fixes that reduced real-vault query p95 dramatically

Important current state:

- turbovec Phase C wiring is present
- exact-scan scaling has also improved materially
- the remaining question is not “can Phase C be built,” but “when should default-policy claims rely on it”

## Storage And Security Rules

Still current:

- `.tvim` files are not harmless cache
- store only under the vault-controlled data area
- do not silently serve stale sidecars
- same-user malware or offline sidecar theft can reveal semantic-similarity structure even though source text is not directly stored

## Manifest Schema

The sidecar manifest remains the fixed contract for the current implementation.

Required fields:

- `vault_id`
- `derived_state_epoch`
- `embedding_model_id`
- `index_version`
- `normalization_version`
- `extraction_version`
- `created_at`
- `updated_at`
- `chunk_count`
- `allocated_slot_count`
- `status`
  - `staging`
  - `published`
  - `unhealthy`
  - `abandoned`
  - `deleting`
- `tvim_path`
- `tvim_size_bytes`
- `bit_width`
- `rebuild_reason`
- `last_error`
- `last_error_at`

## Tests Covered

Current test coverage includes:

- deterministic stable id mapping
- benchmark helper coverage
- published-sidecar semantic search
- corrupt-manifest fail-closed behavior
- startup repair rebuilds
- sidecar route coverage
- source-delete updates
- Phase C auto-backend approval gate
- exact-search cache/hydration scale fix behavior

Primary files:

- `backend/tests/test_turbovec_runtime.py`
- `backend/tests/test_turbovec_benchmark.py`

## Remaining Work

### Still Needed

- broader natural-corpus acceptance benchmarking
- broader user-owned vault evidence for the exact-vs-turbovec decision boundary
- continued threshold tuning confidence on real mixed vaults
- release-ready wording so operators do not confuse “Phase C code exists” with “every large vault should now always prefer turbovec”

### Not Needed Anymore

- no missing Phase C wiring remains
- no missing benchmark endpoint remains
- no missing auto-backend gate remains

## Current Decision Gate

The practical gate is now:

1. keep the existing per-vault approval mechanism
2. collect broader natural-corpus evidence
3. make the explicit default-policy decision for release wording and operator guidance

That is the live remaining plan, rather than the older “reach Phase C next week” framing.
