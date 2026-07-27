# Overall Context

Last updated: 2026-07-27

This file preserves the longer-form current state behind `docs/PROJECT_CONTEXT.md`. It should hold durable background, validation summaries, and high-signal historical notes, not stale architecture claims.

## July 27 ChatGPT MCP, Tunnel, And Reliability Completion

The latest source completes the locally executable implementation in
`docs/CHATGPT_MCP_CONNECTION_PLAN.md`. The remaining release boundary is now explicit:
the owner-deferred Windows package rebuild and its post-build checks, followed by tests
that require an authorized ChatGPT workspace and live OpenAI tunnel credentials.

MCP is divided into three layers. `bridge_mcp_tools.py` owns transport-independent
contracts, annotations, capability filtering, and strict argument validation.
`bridge_mcp_stdio.py` owns bounded newline JSON-RPC framing and concurrent dispatch.
`bridge_mcp.py` owns backend calls, safe error mapping, and result formatting. The
stdio path handles malformed and invalid UTF-8 input, oversized frames, partial EOF,
notifications, duplicate request IDs, cancellation, and overload. Retrieval, writes,
and lightweight calls have separate bounded capacities. Unsafe Unicode controls and
surrogates are rejected, backend resets are mapped to retriable safe errors, and the
entire serialized tool result—not merely one text field—is bounded without cutting
UTF-8 sequences.

The Electron tunnel manager stages only verified packaged helpers, passes a minimal
child environment, rejects non-loopback backend origins and symlinked manifest entries,
and sends the OpenAI runtime key through a temporary file rather than process arguments.
Windows safe storage protects the durable runtime and Bridge credentials. Credential
replacement is atomic, preserves the previous encrypted file on disk-full failure, and
fails closed when OS encryption is unavailable or a newer schema is present. Tunnel
readiness is loopback-only and monotonic-time bounded. Transient DNS, TLS, reset, 429,
and 5xx failures retry with exponential jitter; 401, 403, and version failures stop
automatic reconnect. Rapid disconnect, crash, stale-owner reconciliation, and orphan
cleanup have regression coverage.

Bridge settings and tunnel metadata have explicit compatibility schemas. Existing
Claude Desktop and Cursor clients survive database reopen. A newer Bridge schema is
refused rather than downgraded. Permission-sensitive Bridge client edits rotate the
token automatically; when that client owns the live tunnel, Electron reconnects with
the new token. Resetting setup or deleting the active vault disconnects and forgets
tunnel credentials first. Feature flags exist in both Electron and backend code for
ChatGPT setup, secure tunnel, write tools, future streaming, and future remote HTTP.
Write-disabled deployments downgrade to read-only rather than exposing unusable tools.

Write audit semantics were strengthened. Every recognized client write attempt is
recorded before authorization, including capability and scope denials, stale review
decisions, idempotent replays, and conflicting retries. Successful source captures and
review decisions also record completion. The lightweight `list_clusters` call records
client identity, source count, bytes, and success, allowing the desktop to detect an
actual ChatGPT verification call.

The ChatGPT setup interface is a numbered, resumable flow. It reconstructs its state
from persisted Bridge clients, allowed scope, tunnel metadata, and request history
instead of storing credentials or fragile renderer checkpoints. Copy explains that
workspace eligibility is controlled by ChatGPT and the workspace administrator. It
guides read-only/read-write selection, explicit scope, tunnel health, app/tool scanning,
a harmless `list_clusters` request, a confirmed test artifact for write mode, cleanup,
and immediate disconnect-and-revoke.

The latest source evidence is:

| Gate | Result |
| --- | --- |
| Full backend | 810 passed, 1 optional skip, 2 scale deselections, 0 failed; 286.55 s |
| Focused post-fix MCP/Bridge | 49 passed |
| Desktop | TypeScript passed; 91/91 Electron tests passed |
| MCP Inspector 0.21.2 | Development stdio read-only and read/write passed |
| MCP source soak | 1,000/1,000 calls; init 824.159 ms; tool list 1.552 ms; list p95 86.93 ms; max 160.779 ms; RSS growth 0 MiB |
| Odin scale | 50,000 files; 68.3 MiB peak; 160.824 s under concurrent Inspector load |
| Product scale | 10,000 sources queried in 0.108 s |
| Clean security drill | Pass; locked sources 423; revoked Bridge client 401 |
| Offline-at-rest drill | Pass; zero plaintext marker hits |
| Interrupted-flow drill | Pass before and after recovery |
| Large encrypted vault | 1,200/1,200 imported; 0 failed; query 195.14 ms; reconciliation complete |
| Dependencies | No known Python or production npm vulnerabilities |
| Diff hygiene | Pass; line-ending warnings only |

The first full-suite attempt exposed a direct-call edge case in the new audit preflight:
FastAPI's `Header(None)` sentinel reached token-length validation. The token boundary now
accepts strings only, the focused regression passed, and the clean full rerun produced
the result above. This is retained because it demonstrates why the post-change full
suite cannot be replaced by focused MCP tests.

Machine-readable source evidence is in `tmp/local-validation-20260727/`. Historical
packaged results remain under `tmp/`, but the existing installer predates the final
transport, audit, feature-flag, credential, scope-rotation, and setup-flow changes.
Those artifacts are not proof for the latest source. After the owner rebuilds, packaged
Inspector, soak, runtime/full-vault/OCR/migration, startup, rendered UI, Odin launcher,
package layout, install, and uninstall gates must all be repeated.

## July 26 Desktop Chrome And Model-Onboarding Stabilization

The latest source revision replaces the Windows native title bar with Vault-owned
window chrome. Electron creates a frameless `BrowserWindow`; the renderer reserves
a 32 px draggable strip and supplies minimize, maximize/restore, and close controls.
The IPC bridge resolves the sender's window instead of acting on a global window.
Onboarding, the normal application shell, and startup-repair screens all retain
window controls, while interactive controls are excluded from drag regions. Real
Electron QA at 125% Windows scaling confirmed drag, maximize, and restore behavior
without the former native title bar.

Managed-model setup also received three state-machine corrections. Recommendation
loading is limited to the initial request, so the 750 ms status refresh no longer
flashes `Loading model options`. The backend model row is authoritative for an
active download, preventing stale renderer progress from masking `installed`.
Terminal installed/cancelled notices fade after 1.8 seconds and unmount after 2.4
seconds in both onboarding and Settings. Finally, the Qwen activation probe sends
`/no_think`, disables thinking through chat-template arguments, and permits 32
output tokens. Runtime evidence showed that the old four-token probe could spend
its complete budget on hidden reasoning and then report an empty generation.

Validation includes 57 passing Electron tests, a passing production desktop build,
four focused managed-runtime tests, two focused onboarding QA tests, an
interactive-control audit across 42 TSX files, and a rendered Playwright
active-download-to-installed transition with no console errors. This is source and
development-build evidence. The existing 0.1.9 installer and unpacked application
were produced before this delta and must be rebuilt before package claims include
these changes.

## Current Source Of Truth

- Compact operating brief: `docs/PROJECT_CONTEXT.md`
- Public product overview: `ReadME.md`
- Public benchmark report: `BENCHMARK.md`
- Migration archive: `docs/LORA_TO_RAG_MIGRATION_PLAN.md`

## Current Project Cycle

Vault is currently at version `0.1.9` and in pre-release stabilization and productionization. The core product direction is settled: local-first storage, retrieval-first context delivery, temporal memory, bounded evidence packets, and Odin-backed project context are the active architecture. The current cycle is not a broad feature-discovery phase.

The major scoped implementation passes are complete:

- the live product no longer depends on the former LoRA/expert architecture;
- chat and Bridge use the same grounded context contract;
- clusters have RAG-native indexing and profile lifecycles;
- temporal memory has persisted version history, provenance, user controls, and local refresh;
- Odin supports scoped project registration, durable synchronization, AST-derived structure, retrieval activation, CLI access, project-backed clusters, scoped questions, and request-only graph/tree artifacts;
- the desktop has first-class Projects, Tasks, Sources, cluster profiles, Settings Health, CLI Access, and evidence follow-up surfaces;
- benchmark tooling now separates ingestion, retrieval, packing, reading, judging, and reporting with resumable artifacts and regression gates;
- external-corpus validation now includes all 3,045 Open RAG retrieval questions and a frozen 500-question paid QA gate;
- production memory benchmarking now includes a frozen evolving-fact suite and an activation-only paired protocol that reuses unchanged answers and judgments;
- atomic-memory compiler v9 now runs in production chat-session sync, persists lossless facts and terminal source-unit coverage separately from the curated temporal ledger, exposes session-scoped loading, and records conservative named-entity category memberships for future retrieval activation;
- the public README and benchmark report describe the product and its measured results in user-facing language;
- the July 24 UI distillation removed redundant cluster inspectors, dead/stale controls and components, duplicate navigation, and several spacing/overflow failures while preserving a smaller explicit accessibility and packaged-desktop backlog;
- the July 26 desktop pass added frameless app-integrated Windows controls and corrected managed-model activation, polling, and terminal-notice behavior.

The remaining cycle is release work and quality productionization:

1. publish the active 0.1.9 frameless-shell, model-onboarding, and MCP source;
2. preserve the completed backend, desktop, Inspector, security, scale, dependency,
   and source-soak evidence while the owner prepares the package rebuild;
3. prove a production-shaped compressed late-interaction index before considering ColBERT activation;
4. evaluate future memory changes on fresh, preregistered evidence rather than the development-exposed LongMemEval set;
5. improve Odin's TypeScript/React graph-to-prompt selection and authoritative cross-file relationships;
6. rebuild the Windows installer from the latest source and complete
   account-separation and signing validation;
7. finish the remaining UI audit work in packaged Electron: accessibility, keyboard/zoom, offline and lock transitions, remaining stale route handlers, and Bridge/Settings decomposition.

The reviewed 0.1.9 packaging pass is published on `main`. GitHub CI run
`30182242079` passed the dependency audit, desktop, quick, integration, system,
and benchmark jobs; the dispatch-only Odin scale job was correctly skipped. The
development/test installer lifecycle passed. The project remains pre-release
because the latest source still needs a package rebuild and account-separation
and signing proof remain outstanding.

The July 21 atomic-memory v8 pass closes the production-ingestion disconnect identified in the v7 review. `sync_chat_session_temporal_facts` now also regenerates a dedicated atomic tier with immutable source hashes, message provenance, source-unit terminal status, compiler-version state, retraction on source edits, and idempotent resync. Existing temporal retrieval remains unchanged. Generic explicit category counts are normalized as closed cardinalities, and conservative progressive counters support an explicit base such as “I have 4 projects” followed by an unambiguous singular increment. A forced, model-free replay of both frozen 200-question development sets preserved 4/200 and 5/200 activation, 100% activated correctness, zero false-safes, and 100% source-unit coverage. This is a production capability improvement, not a benchmark accuracy gain; broader category membership/coreference remains the activation blocker.

The follow-on v9 pass adds explicit title/apposition membership facts and a small general alias ontology: for example, `Dr. Lee` and “Morgan Hale is my physician” produce canonical doctor memberships, while doctor/physician/clinician query aliases are exposed by the question plan. These memberships are deliberately marked open-world, so they improve candidate retrieval but cannot certify a complete distinct count. A privacy-preserving coverage inspector can back up and backfill a chosen local database, then report only aggregate yield and coverage metrics. No populated chat vault was present on the development machine: both discovered application databases had zero sessions/messages. The v9 forced replay preserved the v8 gates at 4/200 and 5/200 activation, 9/9 correctness, zero false-safes, and 100% source coverage; readiness remains NO-GO solely on activation.

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

- current combined backend collection: `810 passed`, `1 optional skip`, and `2`
  explicit scale deselections, with only the existing Starlette TestClient
  deprecation warning;
- focused backend regression slice: `127 passed`
- Electron behavior tests: `91 passed` on the July 27 source slice
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

- rebuild and repeat clean-machine packaged validation from the latest source;
- prove account separation, vault protection, package integrity, and signed-installer behavior;
- rerun the full backend tier matrix, desktop typecheck/build, Electron tests,
  dependency audit, and packaged smoke tests against the final 0.1.9 tree;
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

The temporal-memory product layer is now operational end to end. A persistent append-only fact ledger stores cluster-scoped versions with immutable speaker/source provenance, citations, validity windows, and supersession links. Extractor v3 covers conservative preference, state, action, plan, identity, locale, role, language, goal, decision, habitual choice, favorite category, and explicit-memory statements; assistant recommendations remain suggestions and cannot become completed user actions. Current facts enter grounded memory packets automatically, while dated questions select the historically valid version.

The product lifecycle around that ledger is also live. General state and preference reversals preserve their histories, written and relative `as of` dates resolve deterministically, and every processed chat session receives a versioned content fingerprint even when it yields no facts. New completed chats enter the ledger through the transcript-memory job. On startup, Vault now detects legacy chat sessions with no state, an older extractor version, or a changed message count and queues one deduplicated local backfill per affected vault. Users can still inspect recent current facts, correct them through immutable replacements, remove them from future answers, inspect aggregate coverage, and start a resumable refresh from Settings > Library storage. The work uses the existing cancellable Tasks queue, skips unchanged current-version conversations, stays behind the unlock boundary, and makes no paid model calls.

Context reduction is now observable on real saved chat turns rather than inferred only from benchmark runs. Retrieval snapshots persist the packing strategy, candidate and selected citation counts, and split estimated token totals for prompt, evidence, history, memory, raw context, and final context. The UI reports aggregate reduction and average final context size without exposing query text or evidence contents. This telemetry is local operational feedback; it does not alter ranking or answers to improve a score.

The current product and benchmark-tooling slice is covered by 593 passing backend tests with 2 intentional skips. The latest desktop TypeScript check and production client/SSR build remains the previously recorded pass; existing bundle-size and external TanStack warnings remain unchanged.

## July 19 Bounded Evidence And Odin Ranking Update

The 10K claim-first LongMemEval v2 run is the frozen full-set baseline: Kimi accepted 409/500 answers (81.8%), the pinned GPT-5.4 judge accepted 410/500 (82.0%), agreement was 97.4%, and no final or cumulative reader request exceeded 10,000 tokens. Mean actual reader-prompt usage was 8,307 tokens, a 75.08% reduction from the earlier 33,332-token mean. This protocol is different from earlier typed-v1 and release-reader runs, so their scores must not be combined.

A deterministic failure dataset now separates retrieval, packing, reading, provider, and judging stages. Of 97 answers rejected by at least one judge, 43 are classified as claim selection or paraphrase, 18 as reader reasoning, 17 as judge/rubric mismatch, 15 as retrieval omission, 2 as judge disagreement, 1 as provider refusal, and 1 as reader truncation. A separate question-family grouping contains 56 temporal, 15 numeric, 9 preference, 9 supersession/latest-state, 6 fact-selection, and 2 cross-session questions. Those family labels derive from question type and wording; they are useful for slicing results but are not causal findings. In particular, they do not establish 56 temporal-resolution defects.

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

## July 20 Shared Claim Semantics And Consolidation

Claim extraction is now shared between production temporal ingestion and bounded benchmark evidence packing. The pure extractor returns only explicit source-verbatim claims and carries their subject, predicate, object, assertion kind, modality, supersession topic, confidence, and citation excerpt. Extractor v3 fixes compound first-person statements such as a positive and negative preference joined in one sentence, and adds conservative forms for `enjoy`, `can't stand`, `would rather`, and named favorite categories. The extractor version bump causes the startup migration detector to queue local idempotent backfills for older session states.

The production memory path now creates a derived consolidation item for preference or explicit history questions only when at least two sessions contribute. Its summary is assembled from structured facts, while its detail retains dated current/superseded labels, exact excerpts, fact IDs, source IDs, session IDs, and validity timestamps. The item never replaces the authoritative facts: individual source-backed temporal items remain available in the same packet. Explicit `as of` queries continue to use the fact version valid at that time rather than mixing a history profile into the answer.

The benchmark packer has a separate opt-in `claim-consolidated-v1` protocol. It atomizes compound claims, anchors all source claims belonging to a cross-session topic, and emits a clearly labeled navigation index only if at least two cited sessions survive packing. The gate compares overall budget, answer-session recall, literal containment, and mean tokens, plus independent recall and containment checks for multi-session and preference questions.

On the frozen 500-question LongMemEval retrieval artifact, consolidated v1 preserved 0.978767 answer-session recall, 0.492 literal containment, and zero over-budget packets. Mean estimated prompt tokens fell from 9,032.54 to 9,004.75, a 0.308% reduction. Multi-session and preference offline recall/containment were unchanged. Only one question formed a cross-session consolidation group, so no paid reader run or accuracy claim is justified from this corpus.

A new deterministic provenance protocol supplies the missing direct coverage. Nine controlled cases test compound preferences, exact and formatting-normalized reversals, a favorite update, a location update, habitual and first-choice paraphrases, user-versus-assistant attribution, and a no-durable-claim input. It measured 9/9 passing cases, 100% exact-claim precision and recall, 100% citation validity, and 100% expected-source retention with zero paid API calls. This fixture is a product regression gate, not a generalization or competitive benchmark.

The next accuracy slice is implemented in the production typed-evidence adapter. Preference questions no longer route through the personalized-advice reducer: a dedicated reducer chooses the latest current cited claim per normalized topic, while explicit history wording admits the previous version. Current preference and advice paths remove superseded rows before reduction. Advice may combine compatible experience and interest anchors across sessions after query-topic filtering, preserving both citations and falling back when either anchor is absent.

Temporal extraction now separates an event expression from the structured object. Completed actions with deterministic day-level expressions (`today`, `yesterday`, an integer number of days or weeks ago, or `on YYYY-MM-DD`) receive a resolved event date with resolution provenance. `last week` is stored as a start/end interval with week precision. State validity is never moved backward from message observation merely because a retrospective sentence contains an older event expression, preventing an old recollection from superseding a newer current state.

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
| Open RAG frozen QA prefix | 500 | 0.9380 section Hit@10 | 83.8% | 73.6% | 2,672.1 | $1.9102 |
| LongMemEval-S typed-v1 | 500 | 0.9802 recall@10 | 83.8% | 83.2% | 33,331.9 | $13.4211 |
| LongMemEval-S claim-first 10K | 500 | 0.9802 recall@10 | 81.8% | 82.0% | 8,307.1 | $4.5111 |
| LoCoMo ColBERT | 1,540 | 0.7606 recall@10 | 66.75% | 63.96% | 650.4 | $1.7388 |

The practical-stat section translates the controlled LongMemEval delta into a 100-question workload. It reports 3.33M versus 0.83M reader prompt tokens, about four times as many questions within the same prompt-token allowance, 19.0 versus 7.5 minutes of equivalent sequential reader latency, and `$2.68` versus `$0.90` in the recorded reader-plus-dual-judge protocol. It also reports the quality cost: roughly 84 versus 82 Kimi-accepted answers and 83 versus 82 GPT-accepted answers per 100. This prevents an efficiency claim from hiding its accuracy tradeoff.

The later Open RAG addition is a distinct document-QA workload. Its 2,672.1 prompt tokens/query is reported separately and is not substituted for the LongMemEval context figure.

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

## July 20 Temporal Activation Isolation

The first production-path LoCoMo temporal-memory experiment used the existing 0.760586-recall@10 ColBERT trace, ingested all ten conversations into Vault's SQLite temporal ledger, retained attributed speaker names, and routed applicable questions through the production typed-evidence adapter. Infrastructure behavior was correct: all 1,540 questions completed, unsupported questions fell back, named-speaker facts retained their provenance, 34 structured contracts were injected, and measured cost remained essentially unchanged at $1.739514.

The aggregate report was not accepted as feature evidence. It showed 0.5306 official token F1, 66.82% Kimi acceptance, and 64.35% GPT-5.4 acceptance, superficially above the earlier 0.5259, 66.75%, and 63.96%. However, 1,506 questions used the unchanged fallback path and the stochastic reader regenerated 577 different hypotheses. Seven responses also ended at the length limit on the first invocation. Aggregate changes therefore conflated reader variance, incomplete retry handling, and the 34 actual feature activations.

Isolation on those 34 activations showed a clear regression. Official F1 fell from 0.6008 to 0.5419. Kimi acceptance fell from 26/34 to 21/34, a 14.71-point loss; GPT-5.4 fell from 22/34 to 21/34. Each activation added 382-1,298 characters of structured text, averaging 658.8. The router had interpreted bounded factual prompts containing preference-adjacent words—especially “favorite”—as distributed preference-synthesis requests. When requested topics did not match extracted facts strongly, the reducer retained tangential preferences instead of returning no contract.

The rejected behavior was corrected in production code rather than hidden in the benchmark. Imported dialogue may still attribute explicit first-person claims to a named speaker, but named-speaker preference routing now requires an explicit aggregate request such as a general preference query. Bounded “favorite” facts remain on ordinary retrieval. Preference contracts now abstain when the requested topic has no provenance-valid match. The subsequent `temporal-ledger-v4` hardening applies that same routing and topic scope to ordinary temporal memory selection and derived consolidation, closing the desktop packet path that previously could still admit unrelated preference items after the typed adapter abstained.

The LoCoMo runner now retries length-limited responses synchronously, increasing the allowance up to a bounded 768-token ceiling, and refuses to generate a report if any response remains truncated. A separate paired evaluator freezes an earlier activation set, reuses baseline hypotheses and judge labels whenever the corrected router falls back, and calls models only for contexts that truly change.

The corrected paired run evaluated the same 34-question set. All 34 former false positives abstained; no reader or judge API calls were made. Official F1 remained exactly 0.6008, Kimi remained 26/34, and GPT-5.4 remained 22/34. The measured regression is closed, but this is abstention and non-regression evidence rather than a new accuracy result. Another full 1,540-question temporal run is not justified until a fresh set contains genuine distributed preference-synthesis questions and the changed subset passes a preregistered paired gate.

Post-change backend verification now passes 644 tests with two intentional skips. The only warning is the existing upstream Starlette TestClient deprecation notice.

## July 20 Evolving-Memory Production Benchmark

A dedicated paired benchmark now exercises the behavior that was too sparse in the frozen 500-question LongMemEval artifact. Dataset protocol `vault-evolving-memory-v1` contains 40 deterministic cases, evenly split across current preferences, preference history, state history, and relative-date completed actions. Each case includes fourteen irrelevant sessions so the reader must distinguish the evolving fact from ordinary conversational activity. The frozen dataset SHA-256 is `ecd4e3141dc2f3772763cba57c609525b8a667207898a8440a5dcd13bf951b64`.

The paired reader protocol holds the question, Kimi K2.6 reader, GPT-5.4 independent judge, and answer rubric constant. Its baseline arm uses the prior unconsolidated claim-first packet. Its candidate arm creates a real temporary Vault database, inserts the conversation sessions and messages, runs production temporal synchronization, retrieves through `get_context_memory`, evaluates the runtime typed-evidence adapter, and injects a bounded contract only when the production path supports it. Deterministic required-fact groups provide a second scorer independent of the LLM judge.

The first smoke exposed two product-path serialization defects rather than hiding them. Resolved relative action dates were stored correctly in `valid_from`, but model-facing detail included both that date and the source word “yesterday”; Kimi could apply the offset twice. Temporal items now present the resolved date in model-facing prose while retaining the exact relative source quotation separately as immutable citation metadata. State-history questions using “before ... now” were not recognized as history requests; the history selector now includes explicit “before” wording and returns dated superseded/current state evidence. Both behaviors have dedicated regression tests.

The final v3 run completed 80 reader/judge arms across all 40 cases with no scorer disagreement:

| Measurement | Legacy claim-first | Production temporal path | Change |
| --- | ---: | ---: | ---: |
| GPT-5.4 judged accuracy | 40/40 (100%) | 40/40 (100%) | No regression |
| Deterministic accuracy | 40/40 (100%) | 40/40 (100%) | No regression |
| Mean reader prompt tokens | 774.725 | 181.250 | **-76.60%** |
| P95 reader prompt tokens | 788 | 276 | **-64.97%** |
| Total reader prompt tokens | 30,989 | 7,250 | **-76.60%** |
| Mean context characters | 1,907.12 | 403.88 | **-78.82%** |
| Estimated uncached reader cost | $0.033248 | $0.010087 | **-69.66%** |

Every category scored 10/10 in both arms. The combined v3 evaluation used 38,239 Kimi prompt tokens and 1,752 Kimi completion tokens across both arms, plus 10,164 GPT-5.4 judge prompt tokens and 320 judge completion tokens. Estimated cost was $0.043335 for Kimi at uncached rates or $0.020368 with reported caching, plus $0.030210 for GPT-5.4 judging. The cache-adjusted total was $0.050578; the all-uncached estimate was $0.073545.

This experiment is a controlled capability and efficiency result. It establishes that the production ledger can preserve answer quality while substantially shortening evidence for the four explicitly covered fact families. It does not establish general conversational-memory accuracy, market leadership, or performance on arbitrary multi-hop questions. The suite and runner live in `scripts/backend/generate_evolving_memory_benchmark.py` and `scripts/backend/evaluate_evolving_memory_api.py`; generated datasets, checkpoints, logs, and reports remain under `.tmp/vault-odin-memory-benchmark`.

The production changes behind the result are broader than benchmark prompt tuning. Shared source-verbatim claim semantics now serve both ingestion and bounded evidence packing. Preference reduction selects the latest cited current fact per normalized topic and admits earlier versions only for explicit history questions. Current preference and advice paths exclude superseded rows. Safe day-level expressions resolve relative to the source timestamp for completed actions, while coarse ranges remain declared metadata. Imported dialogue of the form `Name said, "..."` can attribute explicit first-person claims to that named subject without converting assistant suggestions into user actions. These behaviors preserve original citations and fall back whenever the structured contract is unsupported or insufficient.

The subsequent LoCoMo activation audit narrowed the production boundary further. Surface words such as “favorite” are not sufficient evidence that a question requests distributed preference synthesis. Named-speaker routing now requires an explicit aggregate preference request, and topic matching must find provenance-valid evidence or abstain. `temporal-ledger-v4` records this routing contract across both the typed adapter and the shared chat/Bridge memory packet. The evolving-memory suite remains the current positive controlled result; the corrected LoCoMo paired run remains a neutral typed-contract abstention result, supplemented by a deterministic production-bundle regression for the shared packet path. Both are required context for future temporal-memory promotion decisions.

Current benchmark artifacts and protocol responsibilities are:

- `evaluate_vault_locomo_api.py`: full retrieval/reader/dual-judge evaluation, optional production-temporal routing, persistent dialogue ledger, named-speaker ingestion, synchronous bounded length retry, and report blocking on unresolved truncation;
- `evaluate_locomo_temporal_paired.py`: frozen activation-only comparison that reuses unchanged hypotheses and judgments, checkpoints only changed paths, and reports paired wins/losses and incremental cost;
- `evaluate_evolving_memory_api.py`: paired legacy-versus-production evaluation for explicit evolving-fact families;
- `generate_evolving_memory_benchmark.py`: deterministic generation and hashing of the 40-case controlled corpus.

The promotion state is therefore precise: explicit evolving preferences, state histories, and relative action dates pass their controlled product-path regression gate; broad LoCoMo preference routing failed and was removed; conservative fallback is verified; positive distributed synthesis still needs a fresh preregistered evaluation set before another full paid LoCoMo temporal run.

## July 21 Atomic-Memory Readiness And Offline Evaluation

The architectural hypothesis was that Vault leaves accuracy on the table by asking the query-time reader to extract, attribute, date, deduplicate, and synthesize raw session text simultaneously, whereas systems such as Mem0 perform much of that work during ingestion. The atomic-memory work therefore moved question-independent fact compilation to write time and required the query path to activate only when an operation-specific evidence contract proves completeness.

The production-shaped compiler now retains a lossless source envelope plus deterministic semantic facts with speaker, session, turn, observation/event dates, quantities, state/supersession identity, and immutable source citations. Every source unit has a terminal `facts_extracted` or `processed_no_fact` outcome and a content hash. The question-only planner reads no benchmark question-family label; it plans current-state, state-comparison, list/count, numeric, temporal-difference, or event-order operations from ordinary question text and retrieved-session count.

The evaluation infrastructure was hardened before further paid work. Coverage, reader, and judge stages use content fingerprints; impact-only replays merge unchanged rows; packet diffs identify exactly which reader inputs changed; reader and judge checkpoints invalidate only when their own inputs change. Local neural benchmarks are CUDA-fail-closed on the RTX 3060 Laptop GPU using PyTorch 2.12.0+cu130. Deterministic JSON parsing and contract evaluation remain CPU work because they invoke no neural model. A cache-version failure during v6 proved that fact-cache schema versions must advance whenever compiled fact semantics or unit typing changes; v7 performs that invalidation.

The development sequence matters:

- The earlier v4 baseline safely activated 3/200 representative and 2/200 former-final questions.
- v5 added source-unit accounting, grouped-number parsing, grammatical quantity subjects, date/state normalization, unit-family filtering, repeated-event deduplication, and evaluation-only deterministic reference checks. It reached 4/200 on both sets with zero false-safe activations.
- An initially permissive v6 explicit-cardinality rule transiently activated 10/200 and 8/200, but produced three false-safe operations on each set. Local counts were being mistaken for cross-session totals. Those results were rejected rather than promoted.
- Tightening context coverage, related-cardinality history checks, and later-related-fact checks restored zero false-safes. Current-state selection was then restricted to the requested concept and supersession chain, adding one valid former-final activation for the current BBQ-sauce state.
- A clean full replay exposed an aquarium failure: three tank-capacity values were added as fish counts, producing 50 instead of 17. Gallons/liters are now a separate capacity family. Because the implicit singular pleco still is not an explicit count fact, the final system safely falls back instead of inventing the missing operand.

The clean atomic-memory v7 results are:

| Metric | Representative 200 | Former-final 200 |
| --- | ---: | ---: |
| Stored evidence recall | 98.1763% | 98.4709% |
| Packed evidence recall | 86.6261% | 84.7095% |
| Atomic candidates | 119 | 117 |
| Reference-verified safe activations | 4 (2.0%) | 5 (2.5%) |
| False-safe activations | 0 | 0 |
| Activated-question completeness | 100% | 100% |
| Deterministic result correctness | 4/4 | 5/5 |
| Source-unit compiler coverage | 100% | 100% |
| Temporal anchor recall | 98.1132% | 100% |
| Direct-fact recall | 100% | 100% |
| Expected mean prompt tokens | 8,283.92 vs 8,290.75 control | 8,303.97 vs 8,320.81 control |

No reader or judge API calls were made. All gates pass except the preregistered 10% activation/usefulness threshold, so the machine-readable decision remains `no-go`. Running a large reader evaluation now would mostly repeat the claim-first control and would not establish an atomic-memory accuracy gain.

The remaining blockers are semantic rather than retrieval-budget problems:

- implicit cardinality and entity normalization, such as turning “a small pleco” into one cited fish entity without unsafe inference;
- closed-world category membership for genuine “how many different/all” questions;
- progressive and cumulative counters that require identity-aware histories rather than summing snapshots;
- repeated-event identity and deduplication across paraphrases and sessions;
- broader but conservative current-state and supersession normalization;
- coreference, synonyms, and category words absent from the source wording while retaining exact provenance;
- a fresh promotion corpus, because both 200-question manifests are development-exposed and only seven LongMemEval questions remain eligible and untouched under the current rules.

The next gate is unchanged: reach at least 10% safe activation on both development sets with zero false-safe operations, 100% source-unit accounting, and prompt usage below the claim-first control. Only then should a new frozen corpus receive reader and dual-judge evaluation.

## July 22 Local Semantic Ingestion Experiment

An opt-in local-model enrichment tier is now production-wired after deterministic chat
memory sync. It runs as a low-priority, preemptable job, refuses non-loopback LLM
endpoints, stores validated facts in separate versioned session state, and marks that
state stale when source content changes. Bounded overlapping chunks preserve full
session hashes and original turn citations; malformed or unsupported citations are
discarded before persistence. Deterministic memory remains the fallback and source of
record.

The first Qwen3 4B Q4_K_M CUDA pilot targeted the frozen three-session doctor-count
case. User turns took 343.40 seconds total and yielded 36 valid facts, seven overlap
duplicates, and one genuinely invalid excerpt. The model generated useful concise
visit/specialist facts, but no `entity_category` qualifiers and at least one incorrect
completed-visit interpretation. Combined packing used 107 facts / 8,498 estimated
tokens versus 139 / 8,341 for deterministic-only, and both arms still failed the
`closed_world_category_coverage` slot. This supports continued small-fixture
development, not promotion or a large reader/judge benchmark. Full assistant-turn
enrichment is substantially slower on verbose benchmark sessions and remains
idle/background work.

## July 22 API Semantic Extraction Recovery/Control Smoke

The benchmark runner now performs bounded, resumable, provenance-validated cloud
extraction while the production path remains loopback-only. A 12-question set was
frozen from already-exposed evaluation data with one claim-first failure and one control
per LongMemEval family. GPT-5.4 processed all 120 retrieved sessions in 270 requests,
producing 4,089 valid facts and 187 rejected candidates for an estimated $8.7551.

Coverage did not clear the offline gate: 100% stored evidence recall, 92.8571% packed
evidence recall, zero false-safe packets, but 0/12 safe atomic activations and a larger
mean packet than claim-first. The facts-only reader nevertheless moved from 6/12 to
7/12 dual-judge correctness, with three wins and two losses (McNemar p=1.0). The gains
covered current-value update, preference recommendation, and temporal calculation. The
losses exposed over-broad project identity and a table relationship reduced to an
incomplete Sunday assignment. Two of six controls regressed, so promotion failed.

This is evidence that write-time synthesis can help the reader, but not that a flat
fact store is sufficient. The next semantic compiler must preserve structured
relationships, normalize entity/category identity, prove closed-world set coverage,
and reject loosely related actions before a larger API extraction run is justified.

## July 24 Open RAG External-Corpus Validation

Vault completed retrieval for all 3,045 questions in Vectara Open RAG Bench at frozen dataset revision `63f6b052ff83508b08e242db42263ee708815c26`. Section Hit@1 was 0.640394, Hit@5 was 0.901149, Hit@10 was 0.948440, and document Hit@10 was 0.996059. Mean query latency was 1.0597 seconds and P95 was 1.0648 seconds. Plain-text section Hit@10 reached 0.975444; text-image, text-table, and text-table-image reached 0.899083, 0.912162, and 0.909091. The result establishes strong external document discovery while identifying multimodal section ranking as the clearest retrieval weakness.

The paid QA run used a deterministic first-500 prefix as an explicit spending gate and remains paused before the remaining 2,545 questions. Kimi accepted 419/500 answers (83.8%, Wilson 80.31%-86.77%); GPT-5.4 independently accepted 368/500 (73.6%, Wilson 69.57%-77.27%). Agreement was 86.2% and Cohen's kappa was 0.5947. No reader response was length-limited.

The reader consumed 1,336,031 input and 80,768 completion tokens: 2,672.1 prompt tokens and 2,833.6 total reader tokens per question. Including both judges, recorded usage was 3,357.6 tokens/query. The recorded component estimates sum to $1.910226: $1.428372 reader, $0.130869 Kimi judge, and $0.350985 GPT judge. A legacy aggregate field in the artifact incorrectly remained zero; public documentation uses the component sum.

This is a separate workload from LongMemEval. Open RAG's 2,672.1 prompt tokens/query is numerically 67.8% below LongMemEval claim-first's 8,307.1, but the corpus, question structure, and packed evidence differ. It is therefore a new document-QA efficiency measurement, not a valid cross-benchmark optimization delta. The full retrieval score is publishable; QA must remain labeled as a frozen 500-question prefix pilot.

## July 24 UI Distillation And Verification

The first implementation pass converted the earlier UI backlog into verified reductions. Home activity hierarchy and OCR settings wrapping were normalized. Map now exposes authoritative links, unclustered items, reset behavior, and large-vault mock coverage. The redundant cluster-detail right rail and nonfunctional close button were removed; cluster rows now navigate directly; duplicate cluster-local Map and source/status surfaces were removed. Global Saved chats, the Settings utility rail, the unused legacy `ClusterMap`, 29 unused UI primitives, and a stale Figma export utility were also removed.

The browser audit passed 46 TSX interaction checks and rendered 13 routes at 1440x900 and 768x900, plus the cluster route at 512 px, without page-level overflow, unlabeled controls, browser errors, or failed close/reset interactions. Remaining work is intentionally narrower: source-inspector persistence, stale embedded project/search/chat paths, Bridge and Settings decomposition, keyboard and automated accessibility, 200% zoom, locked/offline behavior, and packaged Electron validation. `docs/UI_UX_DEEP_AUDIT_2026-07-24.md` is the detailed evidence record; `docs/UI_RECOMMENDATIONS_BACKLOG.md` tracks the remaining work.
