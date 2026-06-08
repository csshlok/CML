# Turbovec Integration And Benchmark Plan

Date: 2026-06-07

## Objective

Reach Phase C of the CML `turbovec` rollout by the end of next week while keeping SQLite as the source of truth and using real-document benchmarks to decide whether the rollout should become default.

## Current CML Retrieval Path

Today CML stores chunk text and chunk embeddings in SQLite, then semantic search:

1. embeds the query,
2. loads all eligible chunk rows for the vault/cluster/active tuple,
3. decodes stored embedding JSON,
4. computes cosine similarity in Python,
5. sorts the full scored set,
6. returns the top rows.

Relevant code:

- [backend/app/api/routes/search.py](../backend/app/api/routes/search.py)
- [backend/app/core/embeddings.py](../backend/app/core/embeddings.py)
- [backend/app/core/retrieval_scoring.py](../backend/app/core/retrieval_scoring.py)

## Turbovec Facts Confirmed From Upstream Docs

Primary sources:

- PyPI: <https://pypi.org/project/turbovec/>
- API reference: <https://raw.githubusercontent.com/RyanCodrai/turbovec/refs/tags/py-v0.7.0/docs/api.md>
- README: <https://raw.githubusercontent.com/RyanCodrai/turbovec/refs/tags/py-v0.7.0/README.md>

Confirmed details:

- `turbovec 0.7.0` ships a Windows `win_amd64` wheel for CPython 3.9+.
- `IdMapIndex` supports stable `uint64` ids.
- `IdMapIndex.remove(id)` is O(1).
- `IdMapIndex.search(..., allowlist=...)` supports caller-supplied subsets of ids.
- `write()` / `load()` persist the index in `.tvim`.
- `bit_width` supports `2` and `4`.
- The `.tvim` format stores the quantized core payload plus a `slot_to_id` table; reverse `id -> slot` is rebuilt on load.

## Architecture Decision

Do not replace SQLite with `turbovec`.

Use `turbovec` as a derived vector sidecar:

- SQLite remains authoritative for:
  - source/chunk text,
  - trust metadata,
  - deleted-state filtering,
  - active embedding model,
  - active tuple / derived state epoch,
  - security and repair.
- `turbovec` becomes the fast vector search layer for already-eligible chunk ids.

Locked design decisions:

1. Sidecar identity key is `vault_id + derived_state_epoch`.
2. The sidecar manifest stores the full tuple for diagnostics, not identity.
3. `.tvim` is not encrypted at rest in Phase B.
4. `.tvim` is stored only inside the vault-controlled derived-artifact directory.
5. The sidecar is treated as sensitive derived state.
6. Same-user malware and offline sidecar theft can reveal semantic similarity structure, though not source text directly.
7. Incremental patching is allowed, but rebuild triggers at `15%` churn measured against `allocated_slot_count`.
8. Mid-query sidecar failure must write `status: unhealthy` to the manifest on disk before exact-scan retry begins.
9. Phase C rollout is default-on only for healthy vaults with `>= 10,000` chunks; smaller vaults keep exact scan as the default.

## Proposed CML Phases

### Phase A: Benchmark And Backend Abstraction

Goal: prove whether `turbovec` materially improves large-vault retrieval without changing product behavior.

Build items:

1. Add a vector backend abstraction.
2. Keep current exact SQLite/Python scan as the baseline backend.
3. Add a `turbovec` prototype backend behind a feature flag.
4. Benchmark both against the same ingested real vault.

Exit criteria:

- Reproducible real-vault benchmark exists.
- Result overlap versus current exact scan is measured.
- Index build time, query latency, and persisted index size are recorded.

### Phase B: Derived Sidecar Integration

Goal: make `turbovec` a first-class derived artifact.

Build items:

1. One index identity per `vault_id + derived_state_epoch`.
2. Stable `uint64` id mapping for `source_chunks.id`.
3. Incremental add/remove for source reindex and deletion.
4. Persist sidecar manifest and repair metadata.
5. Keep fallback to current exact scan if the sidecar is missing, stale, or corrupt.

Exit criteria:

- Sidecar indexes rebuild and activate without breaking tuple isolation.
- Chunk deletion removes ids from the active `IdMapIndex`.
- `.tvim` storage policy is explicit: not encrypted at rest in Phase B, stored only in the vault-controlled derived-artifact directory, and documented as sensitive derived state with same-user/offline semantic-leak residual risk.
- Startup repair can detect and rebuild stale/missing sidecar artifacts.

### Phase C: Default Query Path

Goal: use `turbovec` by default when available.

Build items:

1. SQL still selects eligible chunk ids first.
2. `turbovec` searches only that eligible id set via `allowlist`.
3. SQLite hydrates final snippets and metadata for top ids.
4. Benchmark gate decides whether default-on is justified.

Exit criteria:

- Default search path uses `turbovec` only for healthy vaults with `>= 10,000` chunks.
- Exact scan remains the default below `10,000` chunks.
- Exact-scan fallback remains available for repair mode and comparison.
- Benchmarks show acceptable recall overlap and latency wins on real-vault data.

## Storage And Security Rules

The vector sidecar is sensitive derived state. It must follow the same security boundary as other derived artifacts.

Rules:

- Do not treat `.tvim` files as harmless cache.
- Persist the sidecar under the vault-controlled data area.
- Do not encrypt `.tvim` at rest in Phase B.
- Store `.tvim` only in the vault-controlled derived-artifact path.
- Document explicitly that same-user malware and offline sidecar theft can reveal semantic similarity structure, though not source text directly.
- A sidecar mismatch must fail closed to fallback/rebuild, not silently serve stale results.

## Manifest Schema

Before Phase B starts, the sidecar manifest schema is fixed.

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

Definitions:

- `chunk_count` = logical live chunk ids represented by the manifest.
- `allocated_slot_count` = physical slot count currently allocated inside the sidecar.

Rebuild threshold policy:

- incremental patching is allowed for small changes
- full rebuild is required when `adds + deletes >= 15%` of `allocated_slot_count`
- full rebuild is required when `adds alone >= 15%` of `allocated_slot_count`
- full rebuild is required when `deletes alone >= 15%` of `allocated_slot_count`
- full rebuild is always required on epoch change

Failure policy:

- if the sidecar fails mid-query, write `status: unhealthy` to the manifest on disk
- record `last_error` and `last_error_at`
- retry once with exact scan
- future queries must skip that sidecar until repair/rebuild clears the unhealthy state

## Benchmark Program

### Main Benchmark Principle

Benchmark current CML first.

The purpose of the benchmark is not to make `turbovec` look good. The purpose is to discover the actual breaking point of the current backend and compare a prototype sidecar against it.

### Real-Document Benchmark Tracks

1. Real local PDF corpus benchmark
   - ingest real PDFs from the local machine,
   - measure import failures, chunk counts, DB size, and query latency.
2. Replicated real-document scale benchmark
   - use the real local PDF corpus as the seed,
   - replicate real files to reach larger file counts when the machine does not naturally contain enough files,
   - use this only for latency, storage, rebuild, and churn stress, not recall or overlap claims.
3. User-owned mixed-vault benchmark
   - later track for mixed file types, links, markdown, OCR, and external artifacts.

### Benchmark Outputs

For current exact-scan architecture:

- ingestion seconds,
- successful files / failed files,
- source count,
- chunk count,
- average embedding JSON bytes,
- average chunk text bytes,
- DB bytes,
- encrypted blob bytes,
- current-query min/median/max/avg latency,
- process RSS and CPU time.

For `turbovec` prototype:

- build seconds,
- cold sidecar load seconds,
- persisted `.tvim` size,
- 4-bit search/query min/median/max/avg latency,
- explicit timer split:
  - `t_sql`: SQLite eligibility filter time
  - `t_allowlist`: Python rows to `numpy.uint64` allowlist time
  - `t_search`: `turbovec` kernel time
- overlap@k versus current exact scan,
- optional 2-bit comparison later.

## Tests To Add

### Immediate Tests

1. Stable id mapping is deterministic.
2. Query sampling from real chunks produces non-empty benchmark queries.
3. `turbovec` prototype benchmark returns persisted index output and query results.
4. Benchmark scripts include real-PDF discovery and 100K-cost projection fields.

### Phase B/C Tests

1. Sidecar rebuild when tuple changes.
2. Sidecar rebuild when embedding model changes.
3. O(1) delete path removes chunk ids from the active index.
4. Fallback to exact scan when sidecar manifest/index is missing.
5. Startup repair rebuilds corrupt or stale sidecars.
6. Query path never mixes tuple versions in one result set.
7. Allowlist path respects deleted/trust/tuple filtering from SQLite.
8. Mid-query sidecar failure writes `status: unhealthy` durably before exact-scan retry.
9. Rebuild-threshold logic uses `allocated_slot_count`, not only logical `chunk_count`.

## Initial Benchmark Assets Added

- [backend/app/core/turbovec_benchmark.py](../backend/app/core/turbovec_benchmark.py)
- [scripts/backend/benchmark-real-vault-retrieval.ps1](../scripts/backend/benchmark-real-vault-retrieval.ps1)
- [backend/tests/test_turbovec_benchmark.py](../backend/tests/test_turbovec_benchmark.py)

These assets are for Phase A measurement, not for default runtime use yet.

## Current Corpus Reality On This Machine

Initial local discovery under the user profile found approximately:

- `Desktop`: `119` PDFs
- `Documents`: `1` PDF
- `AppData`: `75` PDFs

That is enough to start a real-document benchmark, but not enough by itself for a natural 10K-file corpus. A 10K-file stress run will therefore need either:

- a broader real local corpus if more roots are approved for scanning, or
- controlled replication of real PDFs for scale-only stress measurement.

## Decision Gate For Next Week

By the end of next week, Phase C is justified only if:

1. Current exact-scan benchmark on real PDFs is recorded.
2. A `turbovec` prototype benchmark on the same chunk set is recorded.
3. Natural-corpus overlap@10 average is `>= 0.95`.
4. No individual query falls below `0.85` overlap@10.
5. No individual cluster average falls below `0.88` overlap@10 on the natural corpus.
6. Search-stage latency improvement is at least `3x` on the qualifying benchmark corpus.
7. 4-bit sidecar size is `<= 25%` of current embedding-storage bytes.
8. Cold sidecar load time on minimum-spec hardware is `< 1.5 s`.
9. The fallback and repair story is fully implemented before default-on runtime wiring.
