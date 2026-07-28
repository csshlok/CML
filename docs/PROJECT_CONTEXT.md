# Project Context

Last updated: 2026-07-28

## Purpose

This is the lean operating brief for Vault. It records current truth, the active project phase, and immediate priorities. Detailed history, experiments, and validation results belong in `docs/OVERALL_CONTEXT.md`; public benchmark methodology belongs in `BENCHMARK.md`.

## Product

Vault is a local-first Windows context-management layer. It turns a user's files, notes, links, screenshots, transcripts, folders, and codebases into reusable, cited context for AI.

- Desktop: Electron and React in `apps/desktop`
- Backend: FastAPI in `backend`
- Storage: explicit local vaults backed by SQLite and local indexes
- External access: Bridge, MCP, local HTTP API, and CLI
- Codebase context: Odin project indexing, retrieval, scoped chat, and request-only graph/tree artifacts
- Current version: `0.1.9` pre-release

## Current Project Phase

Vault is in **pre-release stabilization and productionization**.

The scoped RAG migration, temporal memory foundation, Odin project workflow, bounded context pipeline, and primary desktop surfaces are implemented. The project is no longer deciding its core architecture. Current work is about proving release reliability, productionizing the strongest retrieval improvements, improving measured quality without benchmark-specific behavior, distilling the UI around real user journeys, and finishing clean Windows packaging.

The reviewed 0.1.9 product, packaging, CI, and documentation work is published on `main`. GitHub CI run `30182242079` passed every automatic job for product commit `f36f75e1959ac40b783303316265974f037ae1fb`. A development/test NSIS installer completed install, shortcut, registry, launch, and uninstall validation. Version 0.1.9 remains pre-release because signing, Windows account-separation proof, and a release build on the latest source revision remain outstanding.

## July 28 Package-Launch And Model-State Fixes

The July 28 development package exposed a deterministic launch failure in both the
unpacked executable and an installed copy. The main process embedded the 1.64 MB
onboarding wordmark inside an HTML `data:` URL; the resulting roughly 2.2 MB startup
URL was rejected by Chromium with `ERR_INVALID_URL (-300)` before backend startup or
window display. Startup now loads a small `electron/startup.html` document from
`app.asar`, and that document references the same bundled `Container.svg` used by
onboarding. A bounded inline mark remains available if the startup document is
missing. Runtime logging now truncates oversized URL/stack fields, and the packaged
launch smoke test exits promptly with the process exit code and a bounded log tail.

The model onboarding and settings paths now derive readiness from canonical backend
model state rather than treating import completion as activation. Duplicate imports
are reconciled by model identity and artifact path, unusable entries are not presented
as ready, and an already imported usable model can be selected without importing it
again. Regression coverage includes duplicate legacy records and interrupted or
inactive imports.

Current source validation after these changes is clean: the full backend suite passed
with 816 tests and 2 optional skips; desktop TypeScript and all 94 Electron tests pass;
the production renderer build and renderer HTML safety audit pass; and diff hygiene
passes with line-ending warnings only. The existing July 28 installer/unpacked
artifact is intentionally still the failing pre-fix build. The owner-deferred rebuild
and the complete post-rebuild package gates remain required.

## July 28 Profile, Startup, And Chat Reliability Fixes

The durable onboarding profile is now the single authority for the user's display
name and avatar. Settings saves through Electron setup state, the sidebar subscribes
to the same state, and profile media resolves through the managed-media API. The
vault folder name is no longer used as the user name. The startup progress page uses
one onboarding wordmark rather than rendering a second duplicate logo.

Packaged chat logs also exposed a request-stream lifecycle bug. A legacy middleware
originally used to reserve an unfinished chat field still consumed the request body
and replayed the same `http.request` message indefinitely. After the field became
supported the middleware no longer enforced anything, but Starlette's disconnect
listener still received the replayed body and closed otherwise successful answers
before the terminal `done` event. The obsolete middleware has been removed. A new
full-ASGI regression sends a persisted chat request through the real middleware stack
and requires `meta`, `token`, and `done` plus a `completed` generation. The renderer
also reloads the durable timeline if a connection closes at the terminal boundary,
showing a saved or partial answer once instead of appending a false context-error
message.

Current local validation for this source delta is green: 100/100 additional backend
QA tests, including normal completion and client-disconnect persistence; desktop
TypeScript and 95/95 Electron behavior tests; the production renderer build; Python
compile checks; and diff hygiene. The package was not rebuilt, by owner request.

## July 27 MCP, Tunnel, And Reliability Completion

The latest source completes the local ChatGPT MCP connection implementation and the
reliability remediation plan. MCP tool contracts, stdio transport, and backend
handlers are separated across `bridge_mcp_tools.py`, `bridge_mcp_stdio.py`, and
`bridge_mcp.py`. The transport enforces strict schemas, byte bounds, UTF-8 and Unicode
control safety, bounded per-class/global concurrency, cancellation, overload rejection,
graceful EOF, duplicate-ID rejection, safe backend-reset errors, and total serialized
output limits.

Electron now owns an encrypted, supervised outbound Secure MCP Tunnel lifecycle.
Credentials are replaced atomically through OS encryption; transient network failures
retry with bounded jitter while authentication, permission, and version failures stop
reconnect. Helper integrity rejects symlinks, the MCP child receives a minimal
environment and a loopback-only backend origin, and no desktop bearer token enters the
child. Permission edits rotate the scoped Bridge token and refresh an active tunnel.
Deleting an active vault first forgets the tunnel.

Bridge writes have separate attempted/completed audit events, including read-only and
scope denials, conflicts, replays, approvals, and successful captures. The numbered
ChatGPT setup flow reconstructs progress from durable client, scope, tunnel, and audit
state, detects a successful `list_clusters` verification, and explains the confirmed
write test and immediate revoke path with simple copy.

Latest source validation is clean:

- backend: 810 passed, 1 optional skip, 2 explicit scale deselections, 0 failed;
- desktop: TypeScript passed and 91/91 Electron tests passed;
- MCP Inspector 0.21.2: development stdio read-only and read/write passed;
- MCP soak: 1,000 calls, initialization 824.159 ms, `list_clusters` p95 86.93 ms,
  maximum 160.779 ms, and 0 MiB MCP RSS growth;
- Odin scale: 50,000 files, 68.3 MiB peak memory; the concurrent run took 160.824 s;
- product scale: 10,000 sources queried in 0.108 s;
- security: clean, interrupted, offline-at-rest, and 1,200-source encrypted-vault
  drills passed with zero plaintext marker hits and zero import failures;
- dependency audits: no known Python or production npm vulnerabilities;
- diff hygiene: passed with line-ending warnings only.

The existing installer predates these final source changes. The owner will perform the
package rebuild later, so all post-rebuild packaged Inspector, soak, runtime, UI,
startup, Odin launcher, install, and uninstall gates remain pending. Real ChatGPT
workspace and live OpenAI tunnel validation also remain external release gates.

## Current Architecture

Vault is RAG-only. Retrieval is authoritative for facts, citations, dates, names, numbers, and missing-evidence behavior. Chat and Bridge consume the same bounded retrieval-first packet contract. Clusters are retrieval scopes with cached summaries and glossaries, not trained experts.

Temporal memory uses append-only fact versions with immutable speaker/source provenance, citations, validity windows, and supersession links. Runtime adapter `temporal-ledger-v4` supports current and historical preferences, state histories, resolved relative action dates, conservative cross-session advice, and named-speaker attribution for imported dialogue. Preference memory selection and consolidation share the same conservative routing and topic scope, so bounded `favorite` facts stay on ordinary retrieval and topic misses inject no unrelated preferences. Users can review, correct, remove, and locally refresh extracted facts.

Odin indexes approved repository files without executing or modifying project code. It supports persisted `context` and `code` scopes, immutable snapshots, atomic retrieval activation, cancellable jobs, AST-based Tier A/B extraction, CLI CRUD/query commands, project-backed clusters, scoped chat, and a dedicated Projects workspace. Graph and tree results remain hidden unless requested.

## Current Product Status

| Area | State |
| --- | --- |
| Core RAG and cluster lifecycle | Complete for V1 scope |
| Shared chat/Bridge context contract | Complete |
| Temporal fact history and user controls | Extractor v3, runtime ledger v4, cited histories, resolved day-level actions, conservative synthesis routing, and local legacy backfill implemented |
| Lossless atomic memory | Compiler v9 is production-wired; optional loopback-only local semantic enrichment, separate provenance/staleness state, content-free coverage diagnostics, and conservative entity/category aliases are implemented; retrieval activation remains gated |
| Claim-first bounded evidence packing | Shared consolidated v1 semantics pass offline non-regression; paid accuracy promotion remains gated |
| Odin scoped project workflow | Complete for current scope |
| Odin AST extraction | Tree-sitter/Python AST based; Tier A/B corpus deterministic |
| Desktop project, task, source, settings, and health surfaces | Implemented |
| Public README and benchmark report | Updated with LongMemEval, LoCoMo, and Open RAG results and qualified comparisons |
| ColBERT late-interaction retrieval | Compressed 300K proof measured; scoped path remains experimental and not production-enabled |
| Windows installer and clean-machine proof | Historical development/test 0.1.9 lifecycle passed; owner-deferred rebuild, post-rebuild validation, signing, and account separation remain |
| ChatGPT MCP and Secure Tunnel | Source implementation complete; development Inspector, fault/security, and 1,000-call soak pass; rebuilt-package and real-workspace gates remain |
| UI refinement and distillation | July 24 audit fixes, July 26 frameless chrome/model onboarding, and July 27 resumable ChatGPT setup are implemented; broader accessibility and rebuilt-package visual validation remain |

## Recent Desktop And Onboarding Stabilization

- The Windows `BrowserWindow` is frameless. Vault renders one 32 px draggable title region with native-like minimize, maximize/restore, and close controls across the main app, onboarding, and startup-repair surfaces. IPC handlers operate only on the sending window, and interactive controls are explicitly excluded from drag regions.
- Managed-model recommendation loading is now an initial-load state instead of flashing during the 750 ms status poll.
- Model download UI follows the backend model row as the authoritative state. A completed install can no longer be masked by a stale renderer-side `downloading` fallback.
- The compact model-download notice shows a terminal installed/cancelled state briefly, fades after 1.8 seconds, and unmounts after 2.4 seconds. Settings and onboarding use the same behavior.
- The managed Qwen activation probe now disables thinking, uses `/no_think`, and allows 32 output tokens. This prevents the four-token health probe from spending its complete budget on hidden reasoning and then reporting an empty generation.
- These changes pass source/build, focused backend, Electron, rendered-browser, and interactive-control validation. The existing `test-0.1.9-Setup.exe` and `win-unpacked` artifacts were built before this July 26 source delta and must not be represented as containing it.

## Latest Benchmark Snapshot

| Benchmark | Best relevant result | Efficiency |
| --- | --- | --- |
| Open RAG full retrieval, 3,045 questions | 0.6404 section Hit@1; 0.9011 Hit@5; 0.9484 Hit@10; 0.9961 document Hit@10 | 1.0597 s mean / 1.0648 s P95 query latency |
| Open RAG frozen QA prefix, 500 questions | 83.8% Kimi / 73.6% GPT-5.4; 86.2% judge agreement | 2,672.1 reader prompt tokens/query; $1.9102 recorded component cost |
| LongMemEval-S typed-v1, 500 questions | 83.8% Kimi / 83.2% GPT-5.4 | 33,331.9 reader prompt tokens/query |
| LongMemEval-S claim-first 10K, 500 questions | 81.8% Kimi / 82.0% GPT-5.4 | 8,307.1 tokens/query; 0/500 over budget; $4.5111 evaluation cost |
| LongMemEval atomic-memory v9 readiness, two frozen 200-question development sets | 4/200 and 5/200 reference-verified safe activations; zero false-safe activations; readiness remains no-go | 100% source-unit coverage; expected mean prompts 8,283.92 and 8,303.97, both below claim-first controls; 0 reader/judge calls |
| LongMemEval API semantic-extraction smoke, 12 exposed recovery/control questions | Claim-first 6/12 vs facts-only 7/12 dual-judge correct; 3 wins, 2 losses; promotion failed | 120 sessions, 4,089 valid facts, $8.7551 extraction; 0/12 safe activations; facts-only prompts increased |
| Evolving-memory v3, 40 paired questions | 100% baseline and 100% production-path accuracy across four categories | Mean reader prompt fell 774.7 to 181.3 tokens (76.6%); uncached reader cost fell 69.7% |
| LoCoMo ColBERT, 1,540 questions | 0.7606 recall@10; 66.75% Kimi / 63.96% GPT-5.4 | 650.4 reader prompt tokens/query; $1.7388 evaluation cost |
| LoCoMo temporal activation audit, 34 frozen questions | Broad routing regressed Kimi by 14.71 points; conservative routing restored the exact baseline | 34/34 former false positives now abstain; 0 API calls in paired rerun |
| Compressed ColBERT scale, 300K items | 0.7303 recall@10 on 100 controlled global questions | 1.134 GiB; 0.539 s scoped P95 / 0.865 s global P95 |

Claim-first reduced LongMemEval reader prompt volume by **75.08%**, measured reader-plus-dual-judge cost by **66.39%**, and mean reader latency by **60.68%** versus typed-v1, with a 2.0-point Kimi and 1.2-point GPT accuracy tradeoff. At the same workload shape, 100 questions use about 0.83M instead of 3.33M reader prompt tokens. Local benchmark ingestion used zero billable extraction or embedding API tokens.

The shared claim-consolidation pass preserved 0.978767 answer-session recall, 0.492 literal containment, and 0/500 over-budget questions while reducing the offline mean estimate from 9,032.54 to 9,004.75 tokens. It formed a cross-session group on only 1/500 LongMemEval questions, so this is safety and efficiency evidence rather than an accuracy claim. The expanded provenance fixture passed 9/9 cases with perfect exact-claim and citation/source-retention checks.

The dedicated evolving-memory v3 suite freezes 40 questions—10 each for current preferences, preference history, state history, and relative-date actions—with long irrelevant-session distractors. Kimi K2.6 answered both the legacy and production arms at 40/40, confirmed independently by GPT-5.4 and deterministic required-fact checks. Production memory reduced mean prompt tokens by 76.6%, P95 prompt tokens by 65.0%, mean context characters by 78.8%, and estimated uncached reader cost by 69.7%. This validates the explicit fact families under controlled conditions; it is not a general LoCoMo or LongMemEval accuracy claim.

The first production-shaped LoCoMo temporal-memory run activated 34 preference-adjacent questions but reduced activation-slice F1 from 0.6008 to 0.5419, Kimi acceptance from 26/34 to 21/34, and GPT-5.4 acceptance from 22/34 to 21/34. It was rejected. Named-speaker routing now requires an explicit synthesis query, topic misses abstain, and fallback outputs are reused in paired experiments. The corrected frozen rerun changed 0/34 former false positives and exactly preserved all baseline scores at zero API cost. This closes the regression but does not establish a positive LoCoMo accuracy gain.

Atomic-memory v9 is the current LongMemEval development state. Production chat sync compiles every supported message into separate, queryable atomic fact and source-unit tables without flooding the curated temporal-fact index. The compiler types general explicit category counts, materializes conservative progressive totals, and records explicit named-entity category memberships such as doctor/physician aliases. Membership facts remain open-world and cannot independently satisfy a distinct-count closure contract. A forced offline replay changed eight packets in each frozen set but did not change safe activation: 4/200 and 5/200, with all nine results evidence-complete and reference-correct and zero false-safe activations. The preregistered 10% activation gate still fails, so reader and judge evaluation remains blocked.

`scripts/backend/inspect_atomic_memory_coverage.py` now performs backup-protected backfill and emits content-free per-vault measures for session coverage, user-turn fact yield, terminal source-unit coverage, closed cardinalities, and progressive counters. The configured database and the only packaged pre-vault database on the current machine both contain zero chat sessions, so no real-user activation/yield claim is available yet.

The main memory-quality constraint is no longer retrieval or packet budget. It is ingestion-time semantic closure: implicit singular counts, category membership, progressive totals, event identity, and supersession must be normalized before query time. LongMemEval cannot provide another meaningful final split under the current rules because only seven eligible untouched questions remain; both 200-question manifests are development-exposed.

These are benchmark measurements, not universal user-bill guarantees. Model pricing, caching, question complexity, answer length, and judge use change monetary cost. LongMemEval is now development-exposed, so future promotion claims require a preregistered untouched set or another benchmark.

Open RAG supplies that independent external-corpus check for document retrieval. Its complete 3,045-query retrieval result is strong, while the frozen first-500 QA gate exposes remaining multimodal section-selection and answer-judging variance. The 2,672.1 prompt tokens/query is the best measured Open RAG packet size, but it is not directly comparable to LongMemEval's 8,307.1 because the corpus and question shape differ. The paid QA run remains intentionally paused after 500 questions.

## Validation Snapshot

- Latest recorded backend suite: `810 passed`, `1 skipped`, `2 scale tests
  deselected`; one non-blocking Starlette TestClient compatibility warning
- Desktop TypeScript check and production client/SSR build: passed on the latest recorded product slice
- Electron behavior tests: `91 passed`
- Python and npm dependency audits: no known vulnerabilities in the pinned repository environments
- GitHub CI: current action majors, least-privilege read permission, dependency audit, desktop lint/build, four backend tiers, and manual Odin scale gate
- Published CI proof: run `30182242079` passed dependency audit, desktop, quick, integration, system, and benchmark jobs; the manual scale job was correctly skipped
- Odin 50,000-file discovery gate: `160.824 s`, `68.3 MiB` peak traced memory
  while the MCP Inspector ran concurrently; prior isolated result `95.777 s`
- MCP development Inspector: read-only and read/write profiles passed
- MCP source soak: 1,000 calls; `list_clusters` p95 `86.93 ms`; 0 MiB RSS growth
- Product metadata scale: 10,000 sources queried in `0.108 s`
- Latest source security drills: clean, interrupted, offline-at-rest, and 1,200-source
  encrypted vault all passed
- Project/task/evidence UI: passed at the 1024 px minimum against an isolated backend
- npm dependency audit: `0 vulnerabilities`
- Claim-packing CI gate enforces budget, answer-session recall, literal containment, and packet size
- Evolving-memory v3: 40/40 production answers accepted, with 0 scorer disagreements
- Frozen LoCoMo activation correction: exact baseline preservation on 34/34 former false positives with zero API calls
- Atomic-memory v7: two clean 200-question offline replays, 4 and 5 safe activations, zero false-safe activations, and no reader/judge calls
- Open RAG full retrieval: 3,045/3,045 completed; 0.9484 section Hit@10, 0.9961 document Hit@10, and 1.0597 s mean latency
- Open RAG paid QA gate: 500/500 completed with no length finishes; 83.8% Kimi, 73.6% GPT-5.4, and 86.2% judge agreement
- UI distillation browser audit: 46 TSX interaction checks passed; 13 routes rendered at 1440x900 and 768x900 plus the cluster route at 512 px without overflow, unlabeled controls, browser errors, or failed close/reset interactions
- July 26 desktop/model-onboarding delta: production desktop build passed; 57 Electron tests passed; managed-runtime tests passed 4/4; focused onboarding QA passed 2/2; interactive-control audit passed across 42 TSX files; rendered model-download transition completed with zero console errors

## Active Decisions And Boundaries

- Do not restore LoRA/expert runtime paths; the live product is RAG-only.
- Do not enable ColBERT as a universal production retriever. The 300K compressed proof supports an opt-in cluster-scoped path, but global fan-out failed the 850 ms P95 gate and lifecycle, memory, packaging/licensing, migration, deletion, concurrency, encryption, and cross-dataset behavior remain unresolved.
- Treat scoped/global recall equality as controlled synthetic evidence only; it does not prove that relevant cross-cluster evidence can be omitted. Keep a global dense/BM25 fallback in the design.
- Do not optimize only for exposed benchmark questions. Product changes must improve real retrieval, evidence provenance, temporal reasoning, or operating cost and pass regression gates.
- Reuse content-addressed retrieval, compilation, packet, reader, and judge artifacts; during development rerun only questions affected by the changed capability. Reserve full model evaluation for promotion candidates.
- Local model-backed benchmarks require the verified NVIDIA CUDA runtime and must fail rather than silently fall back to CPU. Deterministic parsing, JSON comparison, and contract checks remain CPU-only.
- Atomic-memory cache versions must change whenever write-time fact semantics or unit typing changes; coverage fingerprints alone cannot invalidate already-materialized fact objects.
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

1. Extend ingestion-time atomic normalization for category membership, implicit singular entities, repeated-event/project identity, structured table relationships, progressive counters, and supersession chains; keep the zero-false-safe gate unchanged. The local Qwen3 pilot did not close categories, while the 12-question GPT-5.4 extraction smoke gained three answers but lost two controls and activated 0/12 safe contracts.
2. Raise safe atomic activation to at least 10% on both development sets before any reader/judge evaluation, then freeze a genuinely fresh corpus or benchmark split for promotion evidence.
3. Owner: rebuild and retest the 0.1.9 installer from the latest
   frameless-shell/model-onboarding/MCP source, then complete account-separation and
   signing proof. Rerun packaged Inspector, soak, runtime, UI, startup, Odin, install,
   and uninstall gates against that artifact.
4. Prototype bounded staging plus verified atomic compressed-shard rebuilds, with immediate tombstone filtering, runtime memory-pressure fallback, cross-cluster routing tests, encryption, exact artifact licensing, and a second real corpus before reconsidering ColBERT activation.
5. Create a fresh, preregistered memory-quality set with genuine distributed preference-synthesis, reversal, state-history, temporal-action, category-count, and cumulative-state cases.
6. Improve Odin TypeScript/React graph-to-prompt ranking and authoritative cross-file import/re-export/reference coverage, then rerun multi-model external evaluation.
7. Run the manual Odin scale workflow when the next discovery/indexing change needs promotion evidence.
8. Finish the remaining UI audit items: source-inspector persistence, stale embedded project/search/chat handlers, Bridge and Settings decomposition, keyboard/accessibility coverage, 200% zoom, offline/locked states, and rebuilt-package Electron validation.
9. Execute the seven credentialed ChatGPT/Secure MCP Tunnel gates in
   `docs/CHATGPT_MCP_CONNECTION_PLAN.md` Section 20.7 before broad rollout.

## Canonical References

- Detailed internal state: `docs/OVERALL_CONTEXT.md`
- Public product overview: `ReadME.md`
- Public benchmark methodology and analysis: `BENCHMARK.md`
- UI implementation status and remaining backlog: `docs/UI_UX_DEEP_AUDIT_2026-07-24.md` and `docs/UI_RECOMMENDATIONS_BACKLOG.md`
- Completed migration archive: `docs/LORA_TO_RAG_MIGRATION_PLAN.md`
- Odin implementation: `backend/app/core/projects.py`, `backend/app/core/project_graph.py`, and `backend/app/api/routes/projects.py`
- Temporal memory implementation: `backend/app/core/claim_semantics.py`, `backend/app/core/temporal_facts.py`, and `backend/app/core/typed_evidence_runtime.py`
- Paired memory evaluation: `scripts/backend/evaluate_evolving_memory_api.py` and `scripts/backend/evaluate_locomo_temporal_paired.py`
