# Retrieval Benchmarks

Last updated: 2026-07-24

## Release Gate

Retrieval validation now includes a complete 3,045-question external scientific-document corpus in addition to the original synthetic, scale, and user-owned-vault checks. It is materially stronger than the original Phase 5 synthetic-only state, but clean-machine and broader real-user proof remain part of V1 release validation.

The repo now has:

- synthetic benchmark evidence
- larger-scale benchmark evidence
- broader user-owned real-vault benchmark evidence
- exact-search scale-fix evidence
- turbovec Phase C wiring and benchmark gate coverage
- full Vectara Open RAG Bench retrieval evidence across text, image, and table questions

Remaining release-proof work is broader natural-corpus threshold confidence and clean-machine/release-environment proof around the overall product, not missing basic retrieval instrumentation.

## Current Evidence

| Check | Result | Evidence |
| --- | --- | --- |
| Open RAG full external-corpus retrieval | **Passed with modality headroom** | 3,045/3,045 queries; section Hit@1 `0.640394`, Hit@5 `0.901149`, Hit@10 `0.948440`, document Hit@10 `0.996059`, mean latency `1.0597s`, P95 `1.0648s`; `.tmp\\open-rag-bench\\full-qa-v1\\retrieval-full.json`. |
| Open RAG frozen QA gate | **Completed; full QA remains paused** | First 500 deterministic questions: Kimi `83.8%`, GPT-5.4 `73.6%`, `86.2%` agreement, `2,672.1` reader prompt tokens/query; `.tmp\\open-rag-bench\\full-qa-v1\\qa-full.json`. |
| 100-source retrieval benchmark | Passed | `.tmp\\phase5-retrieval-100\\retrieval-benchmark-report.json` was generated; max query latency was `0.0558s`. |
| 1k retrieval benchmark | Passed | `.tmp\\phase5-retrieval-1k\\retrieval-benchmark-report.json` was generated; max query latency was `0.4679s`. |
| 1500-source retrieval benchmark | Passed | `.tmp\\retrieval-1500-validation\\retrieval-benchmark-report.json` reported `index_seconds=2.7404`, `max_query_latency_seconds=0.5899`, and `15/15` fixtures passing low-spec targets. |
| User-owned real-vault benchmark | Passed on current capped run | `.tmp\\user-owned-vault-broader-validation-v8.json` completed with `400/400` imported, `0` failed, `11764` chunks indexed, and `313.74ms` query p95 after the import and exact-search fixes. |
| Exact-search scale fix | Passed and verified | Repeated exact queries now reuse a cached pre-decoded snapshot and hydrate only top-hit chunk ids; the broader capped repo-root run improved query p95 from `10172.38ms` to `228.85ms` before the final import-quality cleanup pass. |
| Turbovec Phase C wiring | Implemented | Auto-backend gating, sidecar health checks, and per-vault approval benchmark flows are now in product code and covered by `backend/tests/test_turbovec_runtime.py`. |

## Representative Command Evidence

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
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\benchmark-1k-vault.ps1 -ReportRoot .tmp\retrieval-1500-validation -Sources 1500
```

Result:

```text
index_seconds=2.7404; max_query_latency_seconds=0.5899; passing_fixture_count=15/15; passes_low_spec_targets=true
```

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backend\benchmark-user-owned-vault.ps1 -SourceRoot . -MaxFiles 400 -ReportPath .tmp\user-owned-vault-broader-validation-v8.json
```

Result:

```text
supported_count=400; imported_count=400; failed_count=0; chunks_indexed=11764; query_p95_ms=313.74
```

## Current Assessment

Status: materially stronger than the old partial synthetic-only state, but still not the final release-proof endpoint.

What is now true:

- retrieval benchmark evidence is no longer limited to 100 and 1k synthetic runs
- larger-scale and capped real-vault evidence exist
- the exact backend path has already been hardened for larger corpora
- turbovec Phase C is implemented as a gated product path, not a doc-only plan
- Open RAG proves that Vault finds the annotated document in the top 10 for 99.61% and the annotated section for 94.84% of 3,045 external queries
- plain-text section Hit@10 is 97.54%; text-image, text-table, and text-table-image remain lower at 89.91%, 91.22%, and 90.91%

What still remains:

- broader user-owned corpus threshold confidence
- continued mixed-artifact retrieval/chunking evaluation breadth
- the final default-policy confidence story for turbovec-backed large-vault auto mode
- diagnosis of multimodal section misses and the 10.2-point Kimi/GPT QA-judge gap before authorizing the remaining 2,545 paid QA questions
