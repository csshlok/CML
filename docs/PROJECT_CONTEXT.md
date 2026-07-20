# Project Context

Last updated: 2026-07-20

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

Temporal memory uses append-only fact versions with immutable speaker/source provenance, citations, validity windows, and supersession links. Runtime adapter `temporal-ledger-v3` supports current and historical preferences, state histories, resolved relative action dates, conservative cross-session advice, and named-speaker attribution for imported dialogue. Users can review, correct, remove, and locally refresh extracted facts.

Odin indexes approved repository files without executing or modifying project code. It supports persisted `context` and `code` scopes, immutable snapshots, atomic retrieval activation, cancellable jobs, AST-based Tier A/B extraction, CLI CRUD/query commands, project-backed clusters, scoped chat, and a dedicated Projects workspace. Graph and tree results remain hidden unless requested.

## Current Product Status

| Area | State |
| --- | --- |
| Core RAG and cluster lifecycle | Complete for V1 scope |
| Shared chat/Bridge context contract | Complete |
| Temporal fact history and user controls | Extractor v3, runtime ledger v3, cited histories, resolved day-level actions, conservative synthesis routing, and local legacy backfill implemented |
| Claim-first bounded evidence packing | Shared consolidated v1 semantics pass offline non-regression; paid accuracy promotion remains gated |
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
| Evolving-memory v3, 40 paired questions | 100% baseline and 100% production-path accuracy across four categories | Mean reader prompt fell 774.7 to 181.3 tokens (76.6%); uncached reader cost fell 69.7% |
| LoCoMo ColBERT, 1,540 questions | 0.7606 recall@10; 66.75% Kimi / 63.96% GPT-5.4 | 650.4 reader prompt tokens/query; $1.7388 evaluation cost |
| LoCoMo temporal activation audit, 34 frozen questions | Broad routing regressed Kimi by 14.71 points; conservative routing restored the exact baseline | 34/34 former false positives now abstain; 0 API calls in paired rerun |
| Compressed ColBERT scale, 300K items | 0.7303 recall@10 on 100 controlled global questions | 1.134 GiB; 0.539 s scoped P95 / 0.865 s global P95 |

Claim-first reduced LongMemEval reader prompt volume by **75.08%**, measured reader-plus-dual-judge cost by **66.39%**, and mean reader latency by **60.68%** versus typed-v1, with a 2.0-point Kimi and 1.2-point GPT accuracy tradeoff. At the same workload shape, 100 questions use about 0.83M instead of 3.33M reader prompt tokens. Local benchmark ingestion used zero billable extraction or embedding API tokens.

The shared claim-consolidation pass preserved 0.978767 answer-session recall, 0.492 literal containment, and 0/500 over-budget questions while reducing the offline mean estimate from 9,032.54 to 9,004.75 tokens. It formed a cross-session group on only 1/500 LongMemEval questions, so this is safety and efficiency evidence rather than an accuracy claim. The expanded provenance fixture passed 9/9 cases with perfect exact-claim and citation/source-retention checks.

The dedicated evolving-memory v3 suite freezes 40 questions—10 each for current preferences, preference history, state history, and relative-date actions—with long irrelevant-session distractors. Kimi K2.6 answered both the legacy and production arms at 40/40, confirmed independently by GPT-5.4 and deterministic required-fact checks. Production memory reduced mean prompt tokens by 76.6%, P95 prompt tokens by 65.0%, mean context characters by 78.8%, and estimated uncached reader cost by 69.7%. This validates the explicit fact families under controlled conditions; it is not a general LoCoMo or LongMemEval accuracy claim.

The first production-shaped LoCoMo temporal-memory run activated 34 preference-adjacent questions but reduced activation-slice F1 from 0.6008 to 0.5419, Kimi acceptance from 26/34 to 21/34, and GPT-5.4 acceptance from 22/34 to 21/34. It was rejected. Named-speaker routing now requires an explicit synthesis query, topic misses abstain, and fallback outputs are reused in paired experiments. The corrected frozen rerun changed 0/34 former false positives and exactly preserved all baseline scores at zero API cost. This closes the regression but does not establish a positive LoCoMo accuracy gain.

These are benchmark measurements, not universal user-bill guarantees. Model pricing, caching, question complexity, answer length, and judge use change monetary cost. LongMemEval is now development-exposed, so future promotion claims require a preregistered untouched set or another benchmark.

## Validation Snapshot

- Latest recorded backend suite: `608 passed`, `2 skipped`; one non-blocking Starlette TestClient compatibility warning
- Desktop TypeScript check and production client/SSR build: passed on the latest recorded product slice
- Electron behavior tests: `42 passed`
- Python and npm dependency audits: no known vulnerabilities in the pinned repository environments
- GitHub CI: current action majors, least-privilege read permission, dependency audit, desktop lint/build, four backend tiers, and manual Odin scale gate
- Published CI proof: run `29682163820` passed dependency audit, desktop, quick, integration, system, and benchmark jobs; the manual scale job was correctly skipped
- Odin 50,000-file discovery gate: `126.2 s`, `68.3 MiB` peak traced memory
- Project/task/evidence UI: passed at the 1024 px minimum against an isolated backend
- npm dependency audit: `0 vulnerabilities`
- Claim-packing CI gate enforces budget, answer-session recall, literal containment, and packet size
- Evolving-memory v3: 40/40 production answers accepted, with 0 scorer disagreements
- Frozen LoCoMo activation correction: exact baseline preservation on 34/34 former false positives with zero API calls

## Active Decisions And Boundaries

- Do not restore LoRA/expert runtime paths; the live product is RAG-only.
- Do not enable ColBERT as a universal production retriever. The 300K compressed proof supports an opt-in cluster-scoped path, but global fan-out failed the 850 ms P95 gate and lifecycle, memory, packaging/licensing, migration, deletion, concurrency, encryption, and cross-dataset behavior remain unresolved.
- Treat scoped/global recall equality as controlled synthetic evidence only; it does not prove that relevant cross-cluster evidence can be omitted. Keep a global dense/BM25 fallback in the design.
- Do not optimize only for exposed benchmark questions. Product changes must improve real retrieval, evidence provenance, temporal reasoning, or operating cost and pass regression gates.
- Keep benchmark question-family labels separate from root-cause analysis. A temporal question is not automatically a temporal-resolution failure.
- Consolidation must remain derived navigation metadata. Never discard, rewrite, or outrank its immutable cited source claims, and require at least two contributing sessions.
- Current preference/advice reduction must exclude superseded facts. Historical versions are admitted only for explicit change or history questions.
- Preference-adjacent words alone must not activate synthesis. Named-speaker routing requires an explicit aggregate preference request, and a topic miss must fall back without injecting unrelated facts.
- Benchmark reports are blocked while any reader response remains length-limited; fallback hypotheses and judgments must be reused in activation-only experiments so reader variance cannot masquerade as feature impact.
- Resolve event dates only at declared precision: safe day expressions may set completed-action event time, while coarse ranges remain metadata and never silently backdate current state.
- Keep resolved event dates and their verbatim relative citations as separate representations; model-facing evidence receives the resolved date while citation metadata retains the original wording to prevent double application.
- Keep ambiguous dynamic code relationships non-authoritative.
- Keep graphs request-only and project pages focused on status, questions, evidence, and activity.
- Missing local synthesis is a supported retrieval-draft fallback, not a retrieval failure.

## Immediate Next Steps

1. Complete clean-machine Windows installer, account-separation, package-integrity, and signing proof.
2. Prototype bounded staging plus verified atomic compressed-shard rebuilds, with immediate tombstone filtering, runtime memory-pressure fallback, cross-cluster routing tests, encryption, exact artifact licensing, and a second real corpus before reconsidering ColBERT activation.
3. Create a fresh, preregistered memory-quality set with genuine distributed preference-synthesis, reversal, state-history, and temporal-action cases; require a positive or neutral activation-only paired result before another full LoCoMo temporal run.
4. Improve Odin TypeScript/React graph-to-prompt ranking and authoritative cross-file import/re-export/reference coverage, then rerun multi-model external evaluation.
5. Run the manual Odin scale workflow when the next discovery/indexing change needs promotion evidence.
6. Return to the deferred UI audit after backend and benchmark productionization stabilizes.

## Canonical References

- Detailed internal state: `docs/OVERALL_CONTEXT.md`
- Public product overview: `ReadME.md`
- Public benchmark methodology and analysis: `BENCHMARK.md`
- Completed migration archive: `docs/LORA_TO_RAG_MIGRATION_PLAN.md`
- Odin implementation: `backend/app/core/projects.py`, `backend/app/core/project_graph.py`, and `backend/app/api/routes/projects.py`
- Temporal memory implementation: `backend/app/core/claim_semantics.py`, `backend/app/core/temporal_facts.py`, and `backend/app/core/typed_evidence_runtime.py`
- Paired memory evaluation: `scripts/backend/evaluate_evolving_memory_api.py` and `scripts/backend/evaluate_locomo_temporal_paired.py`
