# Project Context

Last updated: 2026-07-19

## Purpose

This is the lean operating brief for Vault. It records current truth, the active project phase, and immediate priorities. Detailed history, experiments, and validation results belong in `docs/OVERALL_CONTEXT.md`; public benchmark methodology belongs in `BENCHMARK.md`.

## Product

Vault is a local-first Windows context-management layer. It turns a user's files, notes, links, screenshots, transcripts, folders, and codebases into reusable, cited context for AI.

- Desktop: Electron and React in `apps/desktop`
- Backend: FastAPI in `backend`
- Storage: explicit local vaults backed by SQLite and local indexes
- External access: Bridge, MCP, local HTTP API, and CLI
- Codebase context: Odin project indexing, retrieval, scoped chat, and request-only graph/tree artifacts
- Current version: `0.1.7` pre-release

## Current Project Phase

Vault is in **pre-release stabilization and productionization**.

The scoped RAG migration, temporal memory foundation, Odin project workflow, bounded context pipeline, and primary desktop surfaces are implemented. The project is no longer deciding its core architecture. Current work is about proving release reliability, productionizing the strongest retrieval improvements, improving measured quality without benchmark-specific behavior, and finishing clean Windows packaging.

The reviewed 0.1.7 product, benchmark, CI, and documentation pass is published on `main` as 10 commits. GitHub CI run `29682163820` passed every automatic job. Version 0.1.7 is still pre-release rather than a release candidate because the manual clean-machine installer, account-separation, signing, and package-integrity gates remain.

## Current Architecture

Vault is RAG-only. Retrieval is authoritative for facts, citations, dates, names, numbers, and missing-evidence behavior. Chat and Bridge consume the same bounded retrieval-first packet contract. Clusters are retrieval scopes with cached summaries and glossaries, not trained experts.

Temporal memory uses append-only fact versions with immutable speaker/source provenance, citations, validity windows, and supersession links. Users can review, correct, remove, and locally refresh extracted facts.

Odin indexes approved repository files without executing or modifying project code. It supports persisted `context` and `code` scopes, immutable snapshots, atomic retrieval activation, cancellable jobs, AST-based Tier A/B extraction, CLI CRUD/query commands, project-backed clusters, scoped chat, and a dedicated Projects workspace. Graph and tree results remain hidden unless requested.

## Current Product Status

| Area | State |
| --- | --- |
| Core RAG and cluster lifecycle | Complete for V1 scope |
| Shared chat/Bridge context contract | Complete |
| Temporal fact history and user controls | Implemented |
| Claim-first bounded evidence packing | Implemented and benchmarked; production behavior remains conservatively gated |
| Odin scoped project workflow | Complete for current scope |
| Odin AST extraction | Tree-sitter/Python AST based; Tier A/B corpus deterministic |
| Desktop project, task, source, settings, and health surfaces | Implemented |
| Public README and benchmark report | Updated with current results and qualified comparisons |
| ColBERT late-interaction retrieval | Compressed 300K proof measured; scoped path remains experimental and not production-enabled |
| Windows installer and clean-machine proof | In progress |
| UI refinement pass | Deliberately deferred until later |

## Latest Benchmark Snapshot

| Benchmark | Best relevant result | Efficiency |
| --- | --- | --- |
| LongMemEval-S typed-v1, 500 questions | 83.8% Kimi / 83.2% GPT-5.4 | 33,331.9 reader prompt tokens/query |
| LongMemEval-S claim-first 10K, 500 questions | 81.8% Kimi / 82.0% GPT-5.4 | 8,307.1 tokens/query; 0/500 over budget; $4.5111 evaluation cost |
| LoCoMo ColBERT, 1,540 questions | 0.7606 recall@10; 66.75% Kimi / 63.96% GPT-5.4 | 650.4 reader prompt tokens/query; $1.7388 evaluation cost |
| Compressed ColBERT scale, 300K items | 0.7303 recall@10 on 100 controlled global questions | 1.134 GiB; 0.539 s scoped P95 / 0.865 s global P95 |

Claim-first reduced LongMemEval reader prompt volume by **75.08%**, measured reader-plus-dual-judge cost by **66.39%**, and mean reader latency by **60.68%** versus typed-v1, with a 2.0-point Kimi and 1.2-point GPT accuracy tradeoff. At the same workload shape, 100 questions use about 0.83M instead of 3.33M reader prompt tokens. Local benchmark ingestion used zero billable extraction or embedding API tokens.

These are benchmark measurements, not universal user-bill guarantees. Model pricing, caching, question complexity, answer length, and judge use change monetary cost. LongMemEval is now development-exposed, so future promotion claims require a preregistered untouched set or another benchmark.

## Validation Snapshot

- Latest recorded backend suite: `593 passed`, `2 skipped`; one non-blocking Starlette TestClient compatibility warning
- Desktop TypeScript check and production client/SSR build: passed on the latest recorded product slice
- Electron behavior tests: `42 passed`
- Python and npm dependency audits: no known vulnerabilities in the pinned repository environments
- GitHub CI: current action majors, least-privilege read permission, dependency audit, desktop lint/build, four backend tiers, and manual Odin scale gate
- Published CI proof: run `29682163820` passed dependency audit, desktop, quick, integration, system, and benchmark jobs; the manual scale job was correctly skipped
- Odin 50,000-file discovery gate: `126.2 s`, `68.3 MiB` peak traced memory
- Project/task/evidence UI: passed at the 1024 px minimum against an isolated backend
- npm dependency audit: `0 vulnerabilities`
- Claim-packing CI gate enforces budget, answer-session recall, literal containment, and packet size

## Active Decisions And Boundaries

- Do not restore LoRA/expert runtime paths; the live product is RAG-only.
- Do not enable ColBERT as a universal production retriever. The 300K compressed proof supports an opt-in cluster-scoped path, but global fan-out failed the 850 ms P95 gate and lifecycle, memory, packaging/licensing, migration, deletion, concurrency, encryption, and cross-dataset behavior remain unresolved.
- Treat scoped/global recall equality as controlled synthetic evidence only; it does not prove that relevant cross-cluster evidence can be omitted. Keep a global dense/BM25 fallback in the design.
- Do not optimize only for exposed benchmark questions. Product changes must improve real retrieval, evidence provenance, temporal reasoning, or operating cost and pass regression gates.
- Keep ambiguous dynamic code relationships non-authoritative.
- Keep graphs request-only and project pages focused on status, questions, evidence, and activity.
- Missing local synthesis is a supported retrieval-draft fallback, not a retrieval failure.

## Immediate Next Steps

1. Complete clean-machine Windows installer, account-separation, package-integrity, and signing proof.
2. Prototype bounded staging plus verified atomic compressed-shard rebuilds, with immediate tombstone filtering, runtime memory-pressure fallback, cross-cluster routing tests, encryption, exact artifact licensing, and a second real corpus before reconsidering ColBERT activation.
3. Create a fresh memory-quality evaluation set; prioritize provenance-aware claim selection, temporal reconciliation, numeric aggregation, preferences, and multi-session synthesis.
4. Improve Odin TypeScript/React graph-to-prompt ranking and authoritative cross-file import/re-export/reference coverage, then rerun multi-model external evaluation.
5. Run the manual Odin scale workflow when the next discovery/indexing change needs promotion evidence.
6. Return to the deferred UI audit after backend and benchmark productionization stabilizes.

## Canonical References

- Detailed internal state: `docs/OVERALL_CONTEXT.md`
- Public product overview: `ReadME.md`
- Public benchmark methodology and analysis: `BENCHMARK.md`
- Completed migration archive: `docs/LORA_TO_RAG_MIGRATION_PLAN.md`
- Odin implementation: `backend/app/core/projects.py`, `backend/app/core/project_graph.py`, and `backend/app/api/routes/projects.py`
