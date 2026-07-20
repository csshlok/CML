# Overall Context

Last updated: 2026-07-19

This file preserves the longer-form current state behind `docs/PROJECT_CONTEXT.md`. It should hold durable background, validation summaries, and high-signal historical notes, not stale architecture claims.

## Current Source Of Truth

- Compact operating brief: `docs/PROJECT_CONTEXT.md`
- Public product overview: `ReadME.md`
- Public benchmark report: `BENCHMARK.md`
- Migration archive: `docs/LORA_TO_RAG_MIGRATION_PLAN.md`

## Current Project Cycle

Vault is currently at version `0.1.7` and in pre-release stabilization and productionization. The core product direction is settled: local-first storage, retrieval-first context delivery, temporal memory, bounded evidence packets, and Odin-backed project context are the active architecture. The current cycle is not a broad feature-discovery phase.

The major scoped implementation passes are complete:

- the live product no longer depends on the former LoRA/expert architecture;
- chat and Bridge use the same grounded context contract;
- clusters have RAG-native indexing and profile lifecycles;
- temporal memory has persisted version history, provenance, user controls, and local refresh;
- Odin supports scoped project registration, durable synchronization, AST-derived structure, retrieval activation, CLI access, project-backed clusters, scoped questions, and request-only graph/tree artifacts;
- the desktop has first-class Projects, Tasks, Sources, cluster profiles, Settings Health, CLI Access, and evidence follow-up surfaces;
- benchmark tooling now separates ingestion, retrieval, packing, reading, judging, and reporting with resumable artifacts and regression gates;
- the public README and benchmark report describe the product and its measured results in user-facing language.

The remaining cycle is release work and quality productionization:

1. stabilize and commit the active 0.1.7 working tree;
2. rerun the complete backend, desktop, packaging, and security gates from a clean state;
3. prove a production-shaped compressed late-interaction index before considering ColBERT activation;
4. evaluate future memory changes on fresh, preregistered evidence rather than the development-exposed LongMemEval set;
5. improve Odin's TypeScript/React graph-to-prompt selection and authoritative cross-file relationships;
6. complete clean Windows installer, account-separation, signing, and package-integrity validation;
7. resume the broader UI refinement pass after backend and retrieval behavior stabilizes.

The reviewed 0.1.7 pass is published on `main` as 10 commits. GitHub CI run `29682163820` passed the dependency audit, desktop, quick, integration, system, and benchmark jobs; the dispatch-only Odin scale job was correctly skipped. The project remains pre-release because clean-machine installer, account-separation, signing, and package-integrity proof are still outstanding.

## Architecture State

The project has completed its migration away from the LoRA cluster-expert path.

The live architecture is now RAG-only:

- retrieval is the evidence authority
- clusters are retrieval scopes with cached profile metadata
- chat and Bridge share a retrieval-first packet contract
- Odin can append bounded, snapshot-proven graph/tree context for explicit internal or external requests without exposing a permanent graph UI
- Odin synchronization runs through immutable candidate manifests and persisted discovery, structure, retrieval, activation, and cleanup jobs; active retrieval membership changes only in the activation transaction
- Odin projects persist either a broad `context` discovery scope or a source-focused `code` scope; the choice is available in the CLI, API, and project settings and is recorded on each snapshot
- Odin CLI access uses desktop-approved scoped clients, a non-secret runtime descriptor, short-lived sessions, and a Windows user-protected credential helper
- Odin structure extraction uses a versioned offline registry for Python, JSON, JavaScript/TypeScript/TSX (including `.mjs`, `.cjs`, `.mts`, and `.cts`), Go, Rust, Java, C#, C, and C++
- token reduction comes from packet shaping and cache reuse, not adapter compression
- desktop setup and packaged runtime no longer expect a second expert runtime

The earlier bundle/expert-compression architecture is historical only and should not be treated as the current product contract.

## What Changed In The Migration

The migration replaced the old `retrieval + LoRA expert` direction with a single RAG stack:

- removed LoRA runtime, training, evaluation, proof, and artifact lifecycle code
- removed expert-oriented cluster statuses and replaced them with RAG-native lifecycle fields
- moved cluster refresh to indexing-driven summary/glossary refresh
- unified chat and Bridge on the same packet shape
- removed onboarding, settings, and packaging assumptions about an expert runtime
- converted the live model recommender path to chat-only compatibility logic

Current cluster metadata now centers on:

- `index_status`
- `profile_status`
- `cluster_summary`
- `cluster_glossary`
- `profile_updated_at`
- `profile_source_hash`
- `indexed_source_count`

## Validation That Passed

The migration has already been validated beyond static code changes.

Live isolated validation passed:

- `search/semantic` returned grounded hits from the seeded RAG vault
- `chat/context` returned grounded citations and retrieval fallback output
- `bridge/context` returned grounded citations and cluster profile data
- desktop screens validated against the isolated backend loaded without console errors on the checked paths

Broader regression validation passed:

- focused backend regression slice: `127 passed`
- Electron behavior tests: `42 passed`
- backend tests are classified automatically into non-overlapping quick, integration, system, benchmark, and scale tiers
- quick: `147 passed`; integration: `214 passed`; system: `120 passed`
- benchmark: `16 passed`, `1 skipped` when optional TurboVec was unavailable
- manually dispatched 50,000-file scale test: `1 passed` in 555.50 seconds
- npm dependency audit: `0 vulnerabilities`
- desktop typecheck and production build passed after the July 13 cleanup

Scale and token-reduction validation passed:

- synthetic user corpus benchmark with `60` files passed
- retrieval benchmark with `500` sources passed
- Odin's reviewed language corpus is deterministic across three runs and preserves unsupported/malformed files for text retrieval
- the opt-in 50,000-file Odin discovery gate passed in `126.2 s` with `68.3 MiB` peak traced memory
- desktop project, Tasks, and answer-evidence interactions passed against an isolated live backend at the 1024 px minimum without page-level horizontal overflow or console errors
- three clean external runs were deterministic for both tools: Odin indexed Flask in a 1.920-second median and Zustand in 1.731 seconds; Graphify 0.9.17 took 31.091 and 10.586 seconds respectively under its different `--code-only` scope
- a six-question local Qwen2.5-1.5B-Instruct evaluation scored Odin graph slices at 0.500 mean fact-group recall, Graphify at 0.458, and no graph at 0.250; the small gap is directional rather than a general quality ranking
- a one-run, code-scope follow-up on Django and React kept file counts within 2.2% and 0.6% between tools; Odin was 8.32x and 7.69x faster with substantially lower sampled process-tree memory, while Graphify retained a broader cross-file relationship vocabulary
- the Django/React Qwen2.5-1.5B-Instruct follow-up scored Odin at 0.333 mean exact fact-group recall, Graphify at 0.167, and no graph at 0.250; only one answer was complete, exposing graph-slice ranking and hallucination grading as the next interpretability bottlenecks
- the release LongMemEval-S pass now covers all 500 cleaned questions: retrieval recall@10 was 0.9802; Kimi K2.6 accepted 83.0% and the pinned GPT-5.4 independent judge accepted 84.8%, with 96.6% judge agreement and Cohen's kappa of 0.8742
- the tokenizer-aware chunker has been projected over all 23,867 LongMemEval sessions: 269,270 chunks, zero above the 240-token target, and 30.8% fewer raw chunk tokens than the release index; the release accuracy numbers remain unchanged until the index is rebuilt and rerun
- LOCOMO's weak single-hop and multi-hop results are not caused by embedding truncation because every dialog-turn document fits the model; widening the existing hybrid candidate pool raises recall from 0.6031 at 10 to 0.7948 at 50, establishing reranking and evidence packing as the next measured optimization
- simple weighted RRF and score-weight tuning did not materially improve held-out LOCOMO recall; a local MiniLM cross-encoder raised recall@10 from 0.5932 to 0.7138 on the canonical 100 and from 0.6031 to 0.7076 on the full 300, but production remains unchanged pending packaging, latency, and source-diversity gates
- AVX2 INT8 ONNX preserved cross-encoder quality and reduced the graph to 23.2 MB, but measured 274-290 ms/query at depth 50 and therefore failed the sub-100 ms production gate; product dependencies remain unchanged
- most LongMemEval multi-session and preference reader failures already had complete gold evidence, which prioritizes structured evidence presentation over speculative consolidation
- the fingerprinted structured reader recovered 9/22 complete-evidence multi-session failures under both judges, compared with baseline acceptance of 2/22 by Kimi and 0/22 by GPT; because the set was selected on GPT failure and recovery missed the 50% gate, a matched previously-correct control is required before production use
- the matched structured-reader control retained 20/22 questions that both judges previously accepted, exactly meeting the 90.9% gate; the balanced failure/control diagnostic gained nine answers and regressed two, but the two count/date aggregation failures require a fresh held-out v2 prompt test before production use
- the fresh 25-question structured-reader v2 holdout failed both preregistered gates: dual-judge retention was 13/18 and recovery was 0/7 with 100% judge agreement; v2 remains experimental and the full-500 rerun was correctly skipped
- preference synthesis and count aggregation now require question-type-specific reader experiments; adding more universal prompt rules is not supported by the evidence
- the Mem0 public harness review favors saved multi-cutoff retrieval, separate predict/evaluate phases, resumability, per-question traces, controlled ablations, and large-scale retrieval tests while reinforcing Vault's use of stricter official judging and independent judge agreement
- routed-reader v3.2 did not pass promotion on a fresh 30-question set that excluded all 69 earlier development/control questions: retention was 17/20 against an 18/20 gate, while recovery was 3/10, every control stratum was at least 80%, judge agreement was 93.3%, prompt tokens were 0.9308x baseline, mean latency was 0.8134x baseline, and routes matched exactly
- the failed retention gate blocked both the tokenizer-safe rebuild and the full-500 paid rerun; the next reader experiment must separately fix cumulative snapshot handling, chronological event ordering, and hard anti-preference filtering before using another untouched holdout
- routed-reader v4 fixed the cumulative-snapshot and chronological-order development regressions, then failed a second fresh promotion set by the same one-control margin: 17/20 retention against 18/20, with 4/10 recovery, 93.3% judge agreement, all control strata at least 80%, prompt tokens at 0.9585x baseline, latency at 0.7964x baseline, zero route mismatches, and zero content filters
- the v4 gate again blocked the tokenizer-safe rebuild and full-500 run; the next memory-reader architecture should type evidence provenance, numeric roles, cumulative state, dates, and preference polarity before deterministic reduction instead of extending the prompt again
- a manual zero-API scoping fixture confirms the typed-evidence boundary: citrus counting and French-press state comparison are fully deterministic once provenance/date/numeric roles are encoded, while slow-cooker advice needs LLM synthesis constrained by required personalized anchors
- a production Kimi/GPT pass on 30 Django and React questions accepted 5/30 Odin answers and 3/30 Graphify answers under GPT-5.4 at a 16,000-character budget; all accepted answers were Django, so React/TypeScript slice ranking remains the active Odin interpretation-quality gap
- required-fact substring matching is retained only as a lexical mention diagnostic because answers can list expected symbols while saying the evidence is missing
- `tree-sitter` is pinned to 0.25.2 because 0.26.0 caused reproducible native access violations on valid external TypeScript/TSX inputs

## Odin Project Context

Odin's scoped release implementation is complete in live code.

The active project contract now separates:

- persisted discovery scope (`context` by default or source-focused `code`)
- accepted manifest freshness
- structure readiness and `active_structure_snapshot_id`
- retrieval readiness and `active_retrieval_snapshot_id`
- optional interpretation, which remains unavailable unless a future local interpretation layer is enabled

Candidate sources have no active cluster membership and use candidate-only chunk state. Discovery and structure may become visible independently, but ordinary retrieval continues to resolve through the prior active snapshot until candidate chunks and membership are activated atomically. This also applies when the discovery scope changes. Cancellation and interrupted-worker reconciliation preserve the prior usable index. Custom include/exclude scopes remain deliberately deferred.

The canonical desktop project route loads aggregate project facts rather than all files or graph nodes. It exposes live progress, cancellation, layer status, freshness, scoped chat entry, run history, folder reconnection, cluster links, layer-specific reindex, and safe removal. Graph/tree views remain on demand. Project-grounded answer citations disclose only the evidence used by that answer, including path, line span, symbol, snapshot/commit, excerpt, and local file actions.

The remaining Odin-adjacent product items are deliberate deferrals rather than incomplete promises: project interpretation, automatic watch/hooks, remote repository indexing, cross-project retrieval until its citation/freshness contract is proven, Tier C languages, and non-Windows credential helpers. Separately, graph-to-prompt definition ranking and typed relationship expansion for TypeScript/React are active quality work identified by the production-model benchmark, not deferred product scope.

## Current Token Reduction Interpretation

The old token-reduction story depended on expert compression. That is no longer true.

The current RAG system reduces tokens through retrieval, evidence selection, and bounded packing:

- selects only relevant evidence
- trims and deduplicates citations
- reuses working memory
- reuses cached cluster profile material
- represents temporal facts and typed claims compactly where their provenance can be preserved
- enforces explicit packet budgets and records packed, final-request, and cumulative usage

There are two distinct measurements and they should not be combined:

1. Earlier product packet telemetry measured `1,858.62` average raw tokens against `1,030.38` final packet tokens, a `44.43%` average reduction. Warm-cache repeat-query behavior measured a `94.8%` reduction in that earlier benchmark. This remains directional operational evidence.
2. The full 500-question LongMemEval comparison is the stronger current controlled result. Claim-first v2 reduced mean reader prompt usage from `33,331.9` typed-v1 tokens to `8,307.1`, a `75.08%` reduction. Cache-adjusted reader-plus-dual-judge cost fell from `$13.4211` to `$4.5111` (`66.39%`), and mean reader latency fell from `11.41 s` to `4.49 s` (`60.68%`). Kimi accuracy moved from `83.8%` to `81.8%`; GPT-5.4 accuracy moved from `83.2%` to `82.0%`.

For a workflow shaped like 100 LongMemEval questions, that means approximately:

| Measurement | Typed-v1 | Claim-first 10K | Difference |
| --- | ---: | ---: | ---: |
| Reader prompt volume | 3,333,190 tokens | 830,710 tokens | 2,502,480 fewer |
| Equivalent sequential reader latency | 19.0 min | 7.5 min | 11.5 min less |
| Recorded reader + dual-judge evaluation cost | $2.68 | $0.90 | $1.78 less |
| Kimi-accepted answers, projected from the full set | About 84 | About 82 | About 2 fewer |

The same reader-prompt allowance therefore supports about four times as many similarly shaped questions under claim-first packing. All 500 measured claim-first questions stayed within both the final and cumulative 10,000-token budget.

The `75.08%` number is a prompt-volume reduction, not a universal bill discount. The `66.39%` cost reduction belongs to the recorded reader-and-two-judge protocol. Normal product use may omit judges, and actual billing varies with model, provider price, cache use, answer length, and source/question complexity.

Benchmark ingestion is local. Parsing and embedding the measured corpora produced zero billable extraction or embedding API tokens. That moves ingestion cost to local CPU, RAM, disk, time, and electricity; it does not make ingestion resource-free.

This is the current product story: Vault reduces repeated corpus replay through grounded selection and bounded context, while exposing the quality and resource tradeoff.

## Remaining Non-Migration Work

The migration is complete. Remaining work is divided into release gates and measured product-quality work.

Release gates:

- complete clean-machine packaged validation on Windows;
- prove account separation, vault protection, package integrity, and signed-installer behavior;
- rerun the full backend tier matrix, desktop typecheck/build, Electron tests, dependency audit, and packaged smoke tests against the final 0.1.7 tree;
- monitor the upstream Starlette TestClient compatibility warning and the existing frontend bundle-size warning;
- keep optional local synthesis setup understandable while preserving retrieval-draft fallback.

Product-quality work:

- build a compressed persistent ColBERT proof of concept with lifecycle, deletion, migration, concurrency, licensing, package-size, RAM, disk, and latency measurements;
- validate late interaction across another corpus before changing production retrieval;
- improve claim selection, temporal reconciliation, numeric aggregation, preference constraints, and multi-session synthesis on a fresh evaluation set;
- expand deterministic typed reducers only where the evidence contract can remain authoritative and cited;
- improve TypeScript/React Odin graph slices and authoritative import, reference, and re-export relationships;
- repeat Odin interpretability evaluation with more than one model and multiple runs;
- resume accessibility and broader UI QA after the backend/retrieval shape stabilizes.

## July 13 Product Integrity Pass

The desktop UI and repository were audited for false, stale, and developer-facing surfaces.

Changes that now define current behavior:

- Home no longer has a health/quick-action/activity right rail; Quick Actions lead into the prompt and Activity follows Suggested Clusters.
- Cluster progress uses real indexed-source ratios and all shared progress components clamp values to `0–100`.
- Settings Health shows live service, library, database, memory-search, local-chat, task, OCR, and hardware results.
- The Map route no longer accepts or substitutes seeded demo content.
- Chat no longer shows a fabricated cluster count when no library is open.
- Onboarding no longer advertises an unimplemented Google account flow.
- Production routes no longer consume seeded state or mock reply generation. The mock vault store is retained as an explicit development fixture, protected by a test that prevents production route/component imports.
- The reusable UI primitive inventory is retained for future feature work; only obsolete product-specific code remains deleted.
- A shared encrypted-source hydration bug was fixed so authorized search, memory, and report paths receive all decrypted fields without restoring plaintext database storage.
- README and live interface copy now address users directly and reserve backend/runtime terminology for advanced settings and diagnostics.
- Historical UI audit, ingestion-reference, and packaging-investigation documents are retained with status notices so their evidence remains available without being mistaken for current implementation truth.

The Odin release plan, parser dependency decision, and external benchmark are local working records intentionally excluded from Git. Implemented behavior and release status remain summarized in `PROJECT_CONTEXT.md`. The desktop includes a first-class Projects navigation destination and lightweight project index; project details remain centered on status, scoped questions, and run activity, with graph/tree artifacts shown only when requested.

Important distinction:

- missing local synthesis runtime is not a migration bug
- it only means chat falls back to retrieval-draft output instead of local grounded synthesis

## Historical Note

The completed migration record remains in `docs/LORA_TO_RAG_MIGRATION_PLAN.md`. Security audit/build records may also retain LoRA references where they document historical threat analysis. Neither is a live product contract. When an archive conflicts with `docs/PROJECT_CONTEXT.md`, the project context document is authoritative.

## July 18 Memory Benchmark Update

The latest typed-v1 LongMemEval-S result is 83.8% with the Kimi judge and 83.2% with the pinned GPT-5.4 independent judge over all 500 questions. Agreement is 97.8%, retrieval recall@10 is 0.9802, and stored typed-evidence citations are 100% valid. Only two questions were answered deterministically, so the 3.94% realized cost improvement is attributable to provider caching rather than broad evidence compression.

LongMemEval and LOCOMO now have separate diagnoses. LongMemEval is chiefly an evidence-presentation, temporal, and synthesis problem because retrieval is already strong. LOCOMO is chiefly a candidate-generation and ranking problem because recall@10 is 0.6031; broader candidates and the validated cross-encoder improve it, but the reranker has not met the desktop latency gate.

The active memory roadmap is: temporal invalidation and explicit fact histories; immutable assistant/user provenance; bounded evidence packing with evidence/scaffolding token accounting; production-grade reranking; broader typed reducers; then full LOCOMO-1540 and BEAM evaluation. Vault's current target user is a developer or knowledge worker who values local ownership and unified code, project, document, and conversational context more than hosted sub-200-ms retrieval or benchmark-leading multi-session accuracy.

The temporal-memory product layer is now operational end to end. A persistent append-only fact ledger stores cluster-scoped versions with immutable speaker/source provenance, citations, validity windows, and supersession links. Extractor v2 covers conservative preference, state, action, plan, identity, locale, role, language, goal, decision, and explicit-memory statements; assistant recommendations remain suggestions and cannot become completed user actions. Current facts enter grounded memory packets automatically, while dated questions select the historically valid version.

The product lifecycle around that ledger is also live. General state and preference reversals preserve their histories, written and relative `as of` dates resolve deterministically, and every processed chat session receives a versioned content fingerprint even when it yields no facts. Users can inspect recent current facts, correct them through immutable replacements, remove them from future answers, inspect aggregate coverage, and start a local resumable refresh from Settings > Library storage. The work uses the existing cancellable Tasks queue, skips unchanged current-version conversations, stays behind the unlock boundary, and makes no paid model calls.

Context reduction is now observable on real saved chat turns rather than inferred only from benchmark runs. Retrieval snapshots persist the packing strategy, candidate and selected citation counts, and split estimated token totals for prompt, evidence, history, memory, raw context, and final context. The UI reports aggregate reduction and average final context size without exposing query text or evidence contents. This telemetry is local operational feedback; it does not alter ranking or answers to improve a score.

The current product and benchmark-tooling slice is covered by 593 passing backend tests with 2 intentional skips. The latest desktop TypeScript check and production client/SSR build remains the previously recorded pass; existing bundle-size and external TanStack warnings remain unchanged.

## July 19 Bounded Evidence And Odin Ranking Update

The 10K claim-first LongMemEval v2 run is the frozen full-set baseline: Kimi accepted 409/500 answers (81.8%), the pinned GPT-5.4 judge accepted 410/500 (82.0%), agreement was 97.4%, and no final or cumulative reader request exceeded 10,000 tokens. Mean actual reader-prompt usage was 8,307 tokens, a 75.08% reduction from the earlier 33,332-token mean. This protocol is different from earlier typed-v1 and release-reader runs, so their scores must not be combined.

A deterministic failure dataset now separates retrieval, packing, reading, provider, and judging stages. Of 97 answers rejected by at least one judge, 43 are classified as claim selection or paraphrase, 18 as reader reasoning, 17 as judge/rubric mismatch, 15 as retrieval omission, 2 as judge disagreement, 1 as provider refusal, and 1 as reader truncation. The main semantic families are temporal resolution (56), numeric aggregation (15), preference synthesis (9), supersession/latest-state (9), fact selection (6), and cross-session synthesis (2).

The evidence-packing prototype now has a thin deterministic ledger aligned with the production temporal and typed-evidence semantics. It records assertion mode, numeric role, event role, source authority, and query overlap; it does not replace authoritative raw evidence or the production temporal-fact store. On an apples-to-apples 500-question offline replay, ledger v3 retained the same 0.978767 answer-session recall, stayed under budget on every question, reduced the mean estimate by 0.5%, and moved literal gold containment from 0.496 to 0.492. That 0.004 change passes the declared 0.01 containment gate but does not establish an accuracy improvement; another paid full-set run is therefore unwarranted.

Odin graph projection now gathers candidates for every meaningful query term before applying a single ranking. Exact source symbols and broad term coverage outrank incidental prefix matches, while test, fixture, generated, and vendor nodes are demoted. Relationship traversal remains limited to extracted or user-confirmed typed edges, preserving evidence provenance. A model-free CI checker now enforces memory packet budget, recall, containment, and size gates.

All 500 LongMemEval items and prior routed-reader holdouts are development-exposed. Future promotion claims need a preregistered untouched partition or a different benchmark. A full standard LoCoMo retrieval pass is the next zero-API breadth check; it measures retrieval generalization, not LongMemEval reader accuracy.

The full LoCoMo breadth check is complete across all 1,540 standard questions. Recall@10 is 0.629493 and the any-evidence hit rate is 0.703776, improving on the earlier 300-question sample rather than collapsing. Mean retrieval latency is 280 ms and P95 is 626 ms. Recall rises to 0.698083 at 20 candidates, 0.739295 at 30, and 0.797389 at 50. Of the evidence-bearing questions, 372 can recover additional evidence solely by moving positions 11–50 into the first ten; 217 still have no annotated evidence in the first 50.

The failure pattern is category-specific. Category 1 has 158 ranking-recoverable questions and 141 with only partial evidence at 50. Category 3 has 32 ranking-recoverable questions and 32 with zero evidence at 50. This means a faster reranker can materially help both, but Category 3 also requires better candidate generation.

Session-diversity caps are negative evidence: every tested cap from one through five results per session reduced recall, so no diversity rule was added. The local INT8 MiniLM cross-encoder improves full-set recall to 0.703600 at depth 30 and 0.680075 at depth 20, with no category regression. Mean combined latency passes the 500 ms gate, but P95 reaches 1.09 s and 1.17 s against the declared 850 ms ceiling. The reranker therefore remains an experimental benchmark component and is not a packaged production dependency. The next ranking experiment needs a smaller/faster model, cached document representations, or a late-interaction design that preserves the measured recall gain without serial cross-encoding latency.

The zero-at-50 failure audit points to semantic mismatch rather than long or unusually temporal questions: failed questions average 0.0488 lexical overlap with their annotated evidence, compared with 0.3438 outside the failure group. A conversational MiniLM drop-in did not solve it; `multi-qa-MiniLM-L6-cos-v1` reduced recall@10 to 0.606677 and increased zero-at-50 failures to 230.

The next architectural experiment succeeded at retrieval level. Exact semantic-only ColBERT using `lightonai/answerai-colbert-small-v1` raised recall@10 to 0.760586 and recall@50 to 0.889430 over all 1,540 standard questions. All four categories improved, zero-at-50 failures fell from 217 to 100, P95 CPU query latency was 75.8 ms, and the uncompressed token-vector index was 10.1141 times the 384-float dense baseline. This passes the preregistered retrieval, category, latency, and storage gates, but remains a prototype until cross-dataset behavior, model licensing/packaging, persistent-index migration, and end-to-end reader quality are verified.

The July 20 compressed-index scale experiment moved this work from an exact in-memory prototype to a persistent 2-bit FastPLAID proof. The primary shard contained the 5,882 real LoCoMo turns plus deterministic vault-like distractors; three additional 50K distractor shards brought the stopped test to exactly 300,000 items. The combined index stored 16,305,967 token vectors in 1.1335 GiB, or 4,057 bytes per item. That is 19.44% of the 5.831 GiB raw float-vector representation and 2.64 times an equivalent one-vector-per-item 384-float dense index. Local GPU encoding accounted for 6.5 minutes and CPU index work for 73.8 minutes, with no paid API ingestion, reader, or judge calls.

On 100 fixed evidence-bearing LoCoMo questions, the 100K monolithic checkpoint produced 0.730278 recall@10 and 0.384981-second P95 global search. At the final scale, routing to the 150K primary shard preserved 0.730278 recall@10 with a 0.538606-second P95. Sequential global fan-out across all four shards also preserved recall in this controlled corpus, and no synthetic result entered the merged top 10, but P95 rose to 0.864851 seconds with a 1.102211-second maximum and 4.45 GiB peak query-process RSS. The global path therefore narrowly fails the existing 850 ms desktop gate. The synthetic corpus validates capacity and operational scaling rather than general real-world retrieval quality or cross-shard score calibration.

Incremental index lifecycle remains the stronger blocker. Five-thousand-item update time rose from 20.4 seconds near creation to 86.2 seconds at 100K. Twenty-five-thousand-item updates took 537.2 and 629.6 seconds and drove process RSS to 5.18 GiB; increasing the centroid-expansion buffer preserved recall but stored the pending append largely uncompressed, while reducing K-means iterations did not improve update time. Sharding bounds rewrite cost, but whole-vault querying transfers cost into latency and memory. The resulting decision is not to activate ColBERT universally. Continue only toward an opt-in, cluster-scoped compressed index with dense/BM25 fallback, and require deletion/compaction, crash recovery, encryption and lock eviction, RAM ceilings, packaging/licensing, and a second real corpus before promotion.

The follow-up review tightened four interpretation boundaries. Equal scoped and global recall is not evidence that active-cluster-only search is universally safe because the added shards contained no annotated cross-cluster evidence. The 4.45 GiB process peak cannot be linearly extrapolated to one million items because allocator behavior, memory mapping, model state, and concurrency were not isolated. The 86.2-second 5K update belongs to the 100K checkpoint, while the two 25K measurements extended the primary shard from 100K to 150K rather than operating at 300K. Finally, the controlled question set does not establish cross-corpus quality or independent-shard score calibration.

The next production-shaped hypothesis is a bounded staging index searched alongside a read-only compressed shard. New and changed records become searchable through staging; canonical live-record filtering and tombstones suppress deleted or revoked content immediately. A background job rebuilds a new compressed shard from canonical source records, verifies its manifest and retrieval smoke tests, and atomically activates it while retaining the old shard for rollback. This remains an experiment because FastPLAID compaction may still rewrite substantial state and require temporary disk amplification. A runtime resource governor must gate initial activation and unload late interaction under sustained memory pressure, falling back to dense/BM25 without losing canonical access. Vault lock must make all derived search state inaccessible and evict loaded index state.

Licensing is only partly resolved. The upstream `answerdotai/answerai-colbert-small-v1` model declares Apache-2.0, and the installed PyLate and FastPLAID distributions contain MIT licenses. The converted `lightonai/answerai-colbert-small-v1` snapshot used in the benchmark does not declare a license in its own metadata. Exact snapshot provenance, notices, hashes, redistribution permission, and packaged size therefore remain shipping gates.

The backend suite remains green after the benchmark and projection tooling: 593 tests pass and 2 skip. The prior raw-content deprecation was fixed; one upstream Starlette TestClient compatibility warning remains non-blocking.

The corrected top-10 ColBERT trace has also completed the full paid reader and dual-judge pass. Across 1,540 questions, official LoCoMo token-F1 is 0.5259, Kimi K2.6 accepts 1,028 answers (66.75%), and pinned GPT-5.4 accepts 985 (63.96%). Judge agreement is 92.01% with Cohen's kappa 0.8238, no reader response terminated for length, and total measured cost is $1.738753. On the exact 300 IDs used by the prior dense-hybrid run, retrieval improves from 0.603056 to 0.764112, token-F1 from 0.4373 to 0.5065, Kimi acceptance from 59.33% to 66.00%, and GPT acceptance from 56.33% to 63.33%. Because the reader was regenerated, the paired result measures the end-to-end system change rather than a deterministic retrieval-only delta.

## July 19 Benchmark And Public Documentation Consolidation

The benchmark story has been consolidated into two public layers:

- `ReadME.md` contains the short product-facing summary: latest headline results, practical workflow implications, comparison boundaries, and a link to the complete report.
- `BENCHMARK.md` contains the analytical record: benchmark suites, protocol stages, model roles, headline tables, charts, category results, full-run lineage, token and cost accounting, budget compliance, failed and rejected experiments, ingestion economics, competitive qualifications, tradeoffs, and local artifact locations.

`BENCHMARK.md` uses the same visual language as the README: the Vault logo, centered title/subtitle, restrained badges, compact navigation, GitHub callouts, tables, Mermaid charts, and a matching footer. The information hierarchy borrows the useful pattern of introducing the suite, then the ingest-to-evaluate workflow, then results and methodology. It does not present experimental internals as user-facing product features.

The public headline table now records:

| Benchmark and configuration | Questions | Retrieval | Kimi | GPT-5.4 | Reader prompt tokens/query | Evaluation cost |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| LongMemEval-S typed-v1 | 500 | 0.9802 recall@10 | 83.8% | 83.2% | 33,331.9 | $13.4211 |
| LongMemEval-S claim-first 10K | 500 | 0.9802 recall@10 | 81.8% | 82.0% | 8,307.1 | $4.5111 |
| LoCoMo ColBERT | 1,540 | 0.7606 recall@10 | 66.75% | 63.96% | 650.4 | $1.7388 |

The practical-stat section translates the controlled LongMemEval delta into a 100-question workload. It reports 3.33M versus 0.83M reader prompt tokens, about four times as many questions within the same prompt-token allowance, 19.0 versus 7.5 minutes of equivalent sequential reader latency, and `$2.68` versus `$0.90` in the recorded reader-plus-dual-judge protocol. It also reports the quality cost: roughly 84 versus 82 Kimi-accepted answers and 83 versus 82 GPT-accepted answers per 100. This prevents an efficiency claim from hiding its accuracy tradeoff.

The public wording explicitly separates:

- prompt-token volume from provider billing;
- benchmark reader-and-judge cost from ordinary product inference cost;
- zero billable API ingestion tokens from zero local resource use;
- retrieval recall from answer correctness;
- the best measured accuracy configuration from the best measured cost-quality configuration;
- prototype retrieval results from production-enabled behavior.

The report deliberately does not claim that every user will save exactly 75.08% or 66.39%. Those are controlled benchmark deltas. Real workloads vary with corpus size, evidence density, question type, model, answer length, caching, and whether evaluation judges are present.

## Current Benchmark Interpretation And Competitive Position

LongMemEval and LoCoMo diagnose different layers:

- LongMemEval retrieval is already strong at 0.9802 recall@10. Most remaining failures are claim selection/paraphrase, temporal resolution, numeric aggregation, preference synthesis, supersession, or reader reasoning after relevant sessions were found.
- LoCoMo remains retrieval-sensitive. Moving from the dense-hybrid baseline to exact semantic-only ColBERT increased recall@10 from 0.629493 to 0.760586, reduced zero-at-50 failures from 217 to 100, and raised end-to-end answer scores on the exact 300-question comparison.

The product therefore needs two different next moves: improve typed, provenance-aware evidence shaping for long-history synthesis, and productionize a compact late-interaction candidate index for conversational retrieval. A single larger prompt or a universal reranker is not supported by the measured evidence.

Published comparisons remain qualified rather than presented as a shared leaderboard:

| System | Published LongMemEval result | Published context figure | Interpretation |
| --- | ---: | ---: | --- |
| Mem0 | 94.4% | 6,787 mean tokens | Higher published accuracy and lower context than Vault; protocol details differ |
| Hindsight | 94.6% | Not paired with its headline | Higher published accuracy; context comparison is incomplete |
| Zep | 90.2% | 4,408 median tokens | Higher published accuracy and smaller reported context; median and mean are not interchangeable |
| Vault claim-first 10K | 82.0% independent judge | 8,307 mean complete reader-prompt tokens | Reproducible bounded local-first result with dual judging |
| Graphify | 76% on 50 questions | Not published | Primarily a code-graph comparator; its memory result is smaller and not protocol-matched |

Vault is not currently state of the art in hosted conversational-memory accuracy or smallest reported prompt size. Its current differentiation is local ownership, zero paid ingestion tokens in the measured pipeline, inspectable bounded evidence, strict dual-judge reporting, temporal fact history, and one workspace spanning documents, conversations, clusters, and Odin code projects.

Odin and conversational-memory benchmarks should remain separate in product claims. Odin's external Flask, Zustand, Django, and React evaluations measure project discovery, graph coverage, speed, and graph-to-model interpretability. LongMemEval and LoCoMo do not invoke Odin and measure Vault's conversational-memory retrieval and evidence pipeline.

## Promotion Rules For The Next Cycle

Future changes should be promoted only when they improve product behavior and satisfy explicit gates:

- no special-case benchmark answer logic or exposed-question tuning;
- no regression beyond declared recall, evidence-containment, token, latency, and previously-correct-answer retention thresholds;
- fresh preregistered questions for accuracy claims because the full LongMemEval set and earlier holdouts are development-exposed;
- saved per-question retrieval, packed evidence, model usage, finish reason, judge output, and failure classification;
- separate local compute/storage costs from billable API tokens;
- preserve raw authoritative evidence and citations when deterministic ledgers or reducers are used;
- keep experimental dependencies out of production until package, license, index lifecycle, resource, and clean-up behavior are proven;
- rerun clean backend, desktop, packaging, and security validation before a release-candidate label.

## July 19 CI And Push Readiness Review

The complete active working tree was reviewed before publication. The previous two GitHub CI runs on `main` had failed for three known assertions: Odin removed-source reconciliation and two tests that expected schema version 10 after schema version 11 shipped. The schema assertions now follow the current migration version. The Odin reconciliation test now verifies the durable contract—no active project membership remains—while accepting either a retained tombstone or physical cleanup after the last reference disappears. Ten repeated local runs pass both cleanup outcomes.

The local CI-equivalent validation now passes:

- quick backend tier: 196 passed;
- integration backend tier: 214 passed;
- system backend tier: 120 passed;
- benchmark backend tier: 63 passed and one optional TurboVec test skipped;
- combined backend collection: 593 passed and two intentional skips, covering all 595 collected tests;
- desktop TypeScript and Electron lint gate: 42 tests passed;
- desktop production client and SSR build: passed;
- npm audit: zero vulnerabilities;
- pinned Python contributor dependency audit: no known vulnerabilities;
- Python compilation and Odin CLI import/help smoke: passed;
- packaged helper manifest and writable-layout audit: 254 entries, no overlaps;
- Markdown/local-link/encoding and `git diff --check` validation: passed;
- repository secret-pattern review: no provider/private-key patterns; generic matches are deliberate test or smoke placeholders;
- GitHub secret scanning: zero open alerts;
- no tracked or intended new file exceeds the repository's 5 MB review threshold.

The dependency review found and fixed disclosed issues before publication. Production/development pins were advanced to compatible fixed releases for Starlette, Pydantic Settings, Cryptography, PyPDF, Pillow, NLTK, Torch, and Setuptools where each applies. The backend suite passed after installing the fixed runtime set. One upstream Starlette TestClient compatibility warning and the existing frontend chunk-size/TanStack build warnings remain non-blocking.

The CI workflow is now aligned with the incoming tree:

- GitHub-maintained actions use the current verified major releases (`checkout@v7`, `setup-node@v7`, `setup-python@v6`, and `upload-artifact@v7`);
- workflow permissions are explicitly limited to read-only repository contents;
- a dedicated dependency-audit job checks both npm and the pinned Python contributor environment;
- benchmark-analysis regressions are assigned to the benchmark tier rather than inflating the quick tier;
- push-to-main, pull-request, manual workflow dispatch, four backend tiers, desktop build, JUnit uploads, and the manual 50,000-file Odin scale gate remain covered.

The first pushed run exposed a platform-sensitive test assumption: it compared an absolute Windows source path even though Odin's canonical relationship is the normalized project-relative path. The test now resolves the source through `project_sources.relative_path`, verifies that the new active membership excludes it, and accepts either a retained tombstone or final physical cleanup. After 10 repeated local passes, the replacement GitHub run passed the quick tier and the complete automatic workflow.

The unreferenced `apps/desktop/public/brand/Container.svg` is a 1.6 MB SVG wrapper around an embedded raster and is not used by the product or documentation. It remains outside the intended commit set rather than being silently deleted or published.
