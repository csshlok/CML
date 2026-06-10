# Retrieval Benchmarks

Date: 2026-06-10

Audit source: `docs/RELEASE_AUDIT.md`

## Release Gate

The release audit treats retrieval validation as part of the public V1 release evidence. It calls out larger user-owned vault benchmarks and broader retrieval threshold tuning as remaining release-risk work.

## Current Evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Desktop build sanity | Passed | `npm run build` completed successfully after rerunning outside the filesystem sandbox. Vite built both client and SSR bundles. |
| 100-source retrieval benchmark | Passed | `.tmp\phase5-retrieval-100\retrieval-benchmark-report.json` and `.md` were written. Max query latency was `0.0558s`; low-spec targets passed. |
| 1k retrieval benchmark | Passed | `.tmp\phase5-retrieval-1k\retrieval-benchmark-report.json` and `.md` were written. Max query latency was `0.4679s`; low-spec targets passed. |
| Backend test baseline | Passed | Full backend suite: `260 passed, 3 skipped` on 2026-06-10. |
| Active embedding filter regression | Fixed and verified | `test_semantic_search_filters_to_active_embedding_model_and_index_version` now passes; exact semantic search uses the active vector-index policy selector. |

## Command Evidence

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\benchmark-retrieval.ps1 -Sources 100 -ReportPath .tmp\phase5-retrieval-100\retrieval-benchmark-report.json
```

Result:

```text
source_count=100; max_query_latency_seconds=0.0558; passes_low_spec_targets=true
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\benchmark-1k-vault.ps1 -ReportRoot .tmp\phase5-retrieval-1k -Sources 1000
```

Result:

```text
source_count=1000; fixture_count=3; passing_fixture_count=15; max_query_latency_seconds=0.4679; passes_low_spec_targets=true
```

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend/tests
```

Result:

```text
260 passed, 3 skipped, 1 warning in 170.08s
```

## Release Assessment

Status: partially release-cleared.

Synthetic 100-source and 1k-source retrieval benchmark gates now have durable local evidence. Public V1 still needs larger user-owned or equivalent natural-corpus benchmark evidence and the turbovec Phase C acceptance benchmark before default-on rollout.
