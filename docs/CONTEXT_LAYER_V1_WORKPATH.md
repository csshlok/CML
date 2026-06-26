# Context Layer V1 Work Path

Last updated: 2026-06-26

## Goal

Public V1 must make CML feel like a real context-management layer between the user and a model:

- capture context from files, links, and conversations
- remember durable facts and decisions outside the model
- retrieve compact relevant context instead of replaying long history
- reduce token cost for both internal chat and external MCP/Bridge clients

This work path turns that goal into an implementation order.

## V1 Outcomes

V1 must ship all of the following:

1. User-facing external conversation and artifact capture.
2. Distilled memory objects beyond raw sources and transcripts.
3. Working-memory updates that summarize what currently matters.
4. Bootstrap memory maps for new vaults and clusters.
5. Token-budgeted compact context packets for Bridge/MCP and internal chat.
6. Model-readable Bridge/MCP packets instead of raw API JSON by default.
7. Reversible packet expansion and packet savings telemetry.
8. Repeatable evals showing recall, grounding, expansion behavior, and token-reduction value.
9. Chat-model hardening against prompt injection, low-trust evidence, and weak-signal synthesis.
10. Dynamic evidence budgeting that scales with hardware, model tier, query type, and trust mode.
11. Retrieval-first chat routing with graceful no-results and embedding-unavailable fallbacks.
12. Content-aware external capture and chunking for code, diffs, logs, structured data, and transcripts.

## Workstreams

### 1. Capture UX

Deliverables:

- Desktop-visible `Save to CML` flow for outside conversations/artifacts.
- Bridge page/operator flow that is not limited to token/client administration.
- Extension capture package with pairing, vault/cluster selection, and visible capture history.
- Shortcut or command-palette action for quick capture.

Primary repo areas:

- `apps/desktop/src/routes/_app.bridge.tsx`
- `apps/desktop/src/components/CommandPalette.tsx`
- `backend/app/api/routes/bridge.py`
- `backend/app/api/routes/extension.py`

Exit criteria:

- A normal user can save an outside AI conversation or generated artifact into a vault without manual API/MCP wiring.

### 2. Distilled Memory Schema

Deliverables:

- New typed memory records for:
  - facts
  - preferences
  - decisions
  - constraints
  - goals
  - tasks
  - open loops
- Vault/cluster ownership and source provenance for each memory item.
- Confidence, freshness, and review state fields.

Primary repo areas:

- `backend/app/core/database.py`
- `backend/app/core/migrations.py`
- `backend/app/schemas.py`
- new service module under `backend/app/core/` or `backend/app/services/`

Exit criteria:

- Distilled memory can be created, listed, updated, invalidated, and linked back to source evidence.

### 3. Memory Extraction And Writeback

Deliverables:

- Extraction from:
  - internal chat sessions
  - external-turn captures
  - captured artifacts
  - selected imported sources
- Reviewable extraction policy with confidence thresholds.
- Stale/update rules when underlying sources change.

Primary repo areas:

- `backend/app/api/routes/chat.py`
- `backend/app/api/routes/bridge.py`
- `backend/app/core/background_jobs.py`
- new memory extraction module

Exit criteria:

- Saved conversations and important sources produce reusable memory items without requiring manual note rewriting.

### 4. Working Memory And Bootstrap Maps

Deliverables:

- Per-vault and per-cluster working-memory summaries:
  - what changed recently
  - what matters now
  - unresolved questions
  - next actions
- Bootstrap map generation when a vault or cluster is first populated.
- Background refresh when important new content arrives.

Primary repo areas:

- `backend/app/core/background_jobs.py`
- `backend/app/api/routes/clusters.py`
- `backend/app/api/routes/vaults.py`
- desktop surfaces for display

Exit criteria:

- A new or returning user can ask for current context without replaying all old chats or files.

### 5. Shared Compact Context Packets

Deliverables:

- Pass-1 MCP packet formatter for `get_cluster_context`:
  - default formatted packet text
  - raw JSON only through explicit `format=json` or debug mode
  - usage instructions for external models
  - citation handles and trust/limit wording
  - basic packet-vs-raw size telemetry
- Pass-2 shared packet builder used by:
  - internal chat
  - Bridge/MCP
  - CLI/export helpers
- Packet structure should combine:
  - distilled memory
  - working memory
  - supporting evidence snippets
  - citations
  - optional expert digest
  - retrieval-authority statement
  - token ledger
  - warnings / trust state
- Bridge writeback quality state for external model responses:
  - grounded
  - partially_grounded
  - ungrounded
  - unknown
  - user_artifact
- Default Bridge/MCP context packet text with:
  - how external models should use the context
  - citation handle rules
  - expert digest authority limits
  - trust and limit explanations
- Strict token budgeting and trimming for external clients, not only internal chat.
- Content-type-aware packet shaping for:
  - prose
  - code
  - logs
  - tables / JSON
  - transcript history
- Reversible compacted items with expansion handles instead of raw full-text by default.
- Shared bundle path for chat and Bridge so retrieval, digest eligibility, token telemetry, and bundle status stay consistent.

Primary repo areas:

- `backend/app/api/routes/chat.py`
- `backend/app/api/routes/bridge.py`
- `backend/app/bridge_mcp.py`
- new context packet builder module
- `docs/BRIDGE_CONTEXT_PACKET_DESIGN.md`

Exit criteria:

- MCP `get_cluster_context` defaults to model-readable packet text; raw JSON is explicit diagnostics mode.
- Pass-1 Bridge/MCP context output is materially smaller and easier for outside LLMs to use than raw source-shaped JSON.
- Internal chat and Bridge/MCP share the same packet builder and compaction rules after the required Pass-2 evidence-model convergence.
- External model responses are not promoted into authoritative memory unless quality-gated.
- Facts and citations remain retrieval-owned even when expert compression is enabled.

### 6. Reversible Expansion And Telemetry

Deliverables:

- Expansion path for packet items:
  - fetch full snippet
  - fetch larger window
  - fetch exact structured table / JSON payload
- Packet telemetry fields:
  - raw token or size estimate
  - compact token or size estimate
  - savings percentage
  - expansion count / expansion rate
- Developer and operator visibility for packet stats in chat/Bridge diagnostics.
- Pass-2 expansion tools for MCP clients so compact packet handles can fetch fuller evidence only when needed.

Primary repo areas:

- `backend/app/api/routes/chat.py`
- `backend/app/api/routes/bridge.py`
- `backend/app/api/routes/diagnostics.py`
- new packet stats / expansion service modules

Exit criteria:

- Compact delivery is the default path.
- Clients can expand only the items they need.
- CML can prove actual packet reduction instead of only asserting it.

### 7. Evals And Release Proof

Deliverables:

- Benchmarks for:
  - token reduction versus raw transcript/source replay
  - retrieval plus memory recall quality
  - grounding / citation quality
  - packet usefulness for external clients
  - expansion rate and expansion usefulness
- Fixture sets for:
  - long conversations
  - old conversations
  - mixed-source vaults
  - conflict/update scenarios

Primary repo areas:

- `backend/tests/`
- `scripts/backend/`
- new docs report under `docs/`

Exit criteria:

- Public V1 can make a defensible claim that CML reduces context loss and token cost.

### 8. Chat-Model Hardening

Deliverables:

- Shared rule that synthesis should see compact evidence packets first, not raw source-shaped payloads by default.
- Extraction-before-synthesis path:
  - extract candidate claims
  - score support/conflict
  - synthesize only from supported claims plus citations
- Stronger synthesis-eligibility gate:
  - default-exclude low-trust evidence from normal synthesis when possible
  - degrade to extract-only or refuse when evidence is too weak, too conflicting, or too hostile
- Explicit contradiction checks across top evidence before final synthesis.
- Clear user-visible failure states for:
  - insufficient evidence
  - conflicting evidence
  - low-trust-only evidence
  - runtime unavailable
- Broader personal-vault sensitive-query detection covering:
  - medical records, doctors, diagnoses, medication, prescriptions, lab results
  - legal documents, contracts, NDAs, lawsuits, attorneys
  - therapy, mental health, counseling, trauma, addiction
  - private correspondence, family, relationships, children
  - employment, HR, salary, performance, termination
  - identity records, passports, licenses, immigration
  - personal safety, abuse, stalking, threats
  - finance and credentials/secrets
- Category-specific trust-gate reasons and warnings for sensitive personal-vault queries.
- Adversarial evaluation set covering:
  - prompt injection in retrieved text
  - malicious external captures
  - OCR corruption
  - dynamic-web hostile pages
  - conflicting source packets
  - sensitive personal-vault prompts with low-trust-only evidence

Approach:

- Treat retrieved source text as hostile evidence and shrink the amount of raw text the model sees.
- Move more reasoning into deterministic retrieval/extraction checks before generation.
- Let the model write the answer, but do not let it decide what evidence is true without structured gates.
- Treat sensitive personal-vault categories as high-risk even when they do not contain secret/finance keywords.

Primary repo areas:

- `backend/app/api/routes/chat.py`
- `backend/app/core/llm_runtime.py`
- `backend/app/core/retrieval_trust.py`
- new synthesis-safety / claim-extraction module
- `backend/tests/`

Exit criteria:

- Prompt-injection resistance is improved by architecture, not only by prompt wording.
- Weak or conflicting evidence degrades safely and visibly.
- Sensitive medical/legal/therapy/private/employment/identity/safety prompts trigger trust-gated handling, not ordinary synthesis.
- Release claims about grounded chat are backed by adversarial fixtures, not only happy-path retrieval tests.

### 9. Dynamic Evidence Budgeting

Deliverables:

- Replace the single fixed evidence budget with a selector driven by:
  - hardware tier
  - active chat model tier
  - query type
  - trust mode
  - expanded-analysis state
- Replace early hard caps on citation count and snippet width with allocator-driven selection from full candidate evidence.
- Preserve a fallback minimum budget for weak/unknown machines.
- Add telemetry for:
  - selected budget
  - widening/narrowing reason
  - evidence tokens before/after allocation
  - citations selected/trimmed
- Align diagnostics and later UI with the selected budget policy.

Approach:

- Treat `llm_context_token_budget` as fallback floor/override, not the final normal policy.
- Choose wider evidence windows on stronger machines and larger approved chat models.
- Narrow automatically when runtime/trust conditions are poor.
- Keep trust and contradiction handling ahead of generation even when budgets widen.

Primary repo areas:

- `backend/app/api/routes/chat.py`
- `backend/app/core/config.py`
- new `backend/app/core/context_budget_policy.py`
- `backend/app/core/llm_runtime.py`
- `backend/tests/`
- `docs/DYNAMIC_CONTEXT_BUDGETING_DESIGN.md`

Exit criteria:

- Higher-capacity machines and higher-quality chat models no longer receive the same fixed evidence ceiling as low-tier setups.
- Budgeting behavior is explainable and observable.
- Wider budgets improve quality without removing safety margins.

### 10. Retrieval-First Intent Routing

Deliverables:

- Replace keyword/default-general routing with a retrieval-first policy.
- Default natural prompts to vault retrieval unless there is an explicit structural route or direct-chat signal.
- Keep `general_chat` for obvious conversational prompts, explicit no-vault requests, and empty-vault cases.
- Add no-citations fallback:
  - attempt direct local LLM answer when runtime is available
  - mark the answer clearly as ungrounded
  - expose the fallback reason in metadata
- Add embedding-unavailable fallback:
  - explain that retrieval is unavailable
  - attempt direct local LLM answer when runtime is available
  - mark the answer clearly as ungrounded
- Add route telemetry:
  - selected route
  - route reason
  - indexed source count
  - retrieval attempted
  - candidate count
  - citation count
  - fallback reason
  - retrieval and generation latency
- Defer semantic classifier work until telemetry proves the need.

Approach:

- Treat false `general_chat` as the more dangerous error because it silently bypasses the user's memory.
- Accept occasional unnecessary retrieval on world-knowledge prompts because empty retrieval can degrade cleanly.
- Avoid embedding-based intent scoring on every turn until there is real failure data, especially for low-spec machines.

Primary repo areas:

- `backend/app/api/routes/chat.py`
- `backend/app/core/llm_runtime.py`
- new or extracted chat intent/routing policy module
- `backend/tests/`
- `docs/RETRIEVAL_FIRST_ROUTING_DESIGN.md`

Exit criteria:

- Natural memory-seeking prompts search the vault by default.
- Empty retrieval produces a useful ungrounded fallback when possible.
- Missing embeddings no longer hard-stop direct chat if a runtime is available.
- Routing behavior is observable and covered by regression tests.

### 11. Content-Aware Source Chunking

Deliverables:

- Detect content profile for external captures and supported imported files:
  - prose
  - conversation
  - markdown
  - code
  - diff
  - log
  - structured JSON/YAML/TOML
  - CSV/TSV tables
  - mixed artifact
- Replace generic word-window chunking for non-prose sources with content-aware chunking:
  - markdown headings and fenced blocks
  - code file/symbol/fenced-block boundaries
  - parser-backed code symbol boundaries through Tree-sitter or lightweight language-specific parsers when heuristics are not good enough
  - diff file and hunk boundaries
  - log event/traceback boundaries
  - structured object or section boundaries
  - CSV/TSV header plus complete row batches
  - transcript speaker-turn boundaries
- Preserve or mark raw captured/imported content so future chunker upgrades can reprocess old sources.
- Record chunking strategy, content profile, and extraction version on derived chunks.
- Add parser-backed symbol chunking for supported code languages when line/block heuristics fail retrieval or coherence tests.
- Add retrieval tests for generated code, local code files, multi-file artifacts, patches, logs, CSV/TSV, Markdown, and structured data.

Primary repo areas:

- `backend/app/api/routes/bridge.py`
- `backend/app/core/embeddings.py`
- new content-aware chunking module
- `backend/tests/`
- `docs/BRIDGE_CONTEXT_PACKET_DESIGN.md`

Exit criteria:

- External generated code, local code files, diffs, logs, CSV/TSV, Markdown, and structured artifacts are not split only by arbitrary word windows.
- Retrieval can return coherent code/diff/log/table/structured evidence units.
- Code retrieval can return coherent function/class/module units for supported languages, using parser-backed chunking when heuristics are insufficient.
- Old captures and imports can be reprocessed when chunking rules change.

### 12. External Response Quality Gate

Deliverables:

- Capture structured Bridge writeback metadata:
  - `context_request_id`
  - packet ID/hash
  - evidence handles included in the packet
  - evidence handles cited/referenced by the external response
  - client name
  - model name
  - expected-context-use flag
  - artifact-vs-answer intent
- Classify external model responses:
  - `grounded`
  - `partially_grounded`
  - `ungrounded`
  - `unknown`
  - `user_artifact`
- Add verifier stages:
  - deterministic packet-handle and source-title checks
  - quote/evidence overlap checks
  - contradiction/unsupported-claim flags where available
  - local LLM or extraction-based verification when deterministic checks are insufficient
- Store raw external transcripts for audit/history without automatically trusting them.
- Mark ungrounded or unknown external answers as low-trust or review-needed.
- Exclude ungrounded or unknown external answers from normal synthesis, distilled-memory extraction, and cluster-expert training unless explicitly approved.
- Add user/operator review path to promote, downgrade, or delete captured external answers.
- Add regression tests for hallucinated external answers, ignored context packets, unsupported claims, and approved promotion.

Primary repo areas:

- `backend/app/api/routes/bridge.py`
- `backend/app/core/retrieval_trust.py`
- `backend/app/core/retrieval_scoring.py`
- new Bridge response verifier module
- `backend/tests/`
- `docs/BRIDGE_CONTEXT_PACKET_DESIGN.md`

Exit criteria:

- Bad outside-model responses cannot silently become authoritative vault memory.
- Verified external answers can still be saved and reused when they are grounded.
- Ungrounded or unknown external answers remain auditable but are excluded from normal synthesis/training until approved.

## Recommended Implementation Order

1. Distilled memory schema
   Reason: packet building, writeback gating, and working-memory summaries all need typed durable memory records first.
2. Memory extraction and writeback
   Reason: chat turns, selected sources, and external captures need a way to populate the new memory layer before packet compaction can use it.
3. Working memory and bootstrap maps
   Reason: shared packets should assemble from durable memory plus current-state summaries, not only raw source excerpts.
4. Shared compact context packets
   Reason: once memory and working-memory objects exist, internal chat and Bridge can converge on one packet/evidence model.
5. Reversible expansion and telemetry
   Reason: compact packets should immediately support targeted expansion and measurable savings once the shared packet exists.
6. Content-aware source chunking
   Reason: better packet shaping and memory extraction depend on coherent retrieval units from structured/code sources.
7. External response quality gate
   Reason: once packets and expansion exist, writeback can reliably track packet IDs, handles, and grounding state before allowing reuse.
8. Chat-model hardening
   Reason: extraction-before-synthesis and contradiction checks should consume the shared packet and grounded memory/evidence model rather than the current split paths.
9. Dynamic evidence budgeting
   Reason: budget policy should allocate across working memory, recent turns, evidence, and expansion once the packet structure is unified.
10. Capture UX
   Reason: once the backend memory/packet/writeback path is stable, the desktop and extension capture UX can bind to a final contract instead of a moving one.
11. Evals and release proof
   Reason: final token-savings and recall claims should be measured against the full converged context layer rather than intermediate states.

## Current Build-Step Status

Completed:

1. Distilled memory schema
2. Memory extraction and writeback
3. Working memory and bootstrap maps
4. Shared compact context packets
5. Reversible expansion and telemetry foundation
6. Content-aware source chunking foundation
7. External response quality gate plus approval loop
8. Chat-model hardening foundation with supported-claim extraction and contradiction-aware degradation
9. Dynamic evidence budgeting
10. Capture UX
   Current state: desktop has the quick-capture sidebar button, command-palette actions, keyboard shortcut, Bridge save/review surfaces, extension pairing/scope/audit/history flows, a packaged MV3 browser extension with page capture, selected-text capture, PDF-url capture, downloaded-file upload, and screenshot upload, plus a live loopback HTTP smoke for the extension-only status/capture/upload contract and a live Chromium popup smoke for the browser UI import/status/upload path.

Still open:

11. Evals and release proof

## Release Rule

Do not treat CML as a finished context-management layer for public V1 until:

- external capture is user-facing,
- distilled memory exists,
- working memory exists,
- MCP `get_cluster_context` defaults to model-readable packet text instead of raw API JSON,
- Bridge/MCP moves toward compact budgeted reversible packets after the packet-format pass,
- packet telemetry proves meaningful reduction,
- external and local code/diff/log/table/structured sources use content-aware chunking,
- external model responses are quality-gated before becoming authoritative memory,
- chat synthesis has explicit trust/conflict degradation paths,
- chat evidence budgeting is dynamic rather than one fixed global ceiling,
- chat routing defaults to retrieval and degrades no-results or embedding-missing states clearly,
- and evals show that the layer improves recall and reduces prompt size.
