# Bridge Context Packet Design

Last updated: 2026-06-13

## Problem

The current MCP Bridge originally returned raw API JSON to external clients. `get_cluster_context` now defaults to a model-readable packet, and `log_external_turn` plus `capture_external_artifact` now default to human-readable capture receipts with raw JSON remaining opt-in.

That makes Claude, Codex, ChatGPT, or any other MCP client spend prompt context on schema plumbing instead of usable context. The consuming model must infer how to interpret fields such as `source_snippets`, trust labels, source metadata, warnings, and relevance scores without being given a stable instruction contract.

This weakens the core CML promise. Bridge should reduce context cost and improve context use, not hand another model a raw database-shaped payload.

## Token-Cost Goal

This change is directly tied to CML's outside-LLM token-cost reduction goal.

The Bridge should not make Claude, Codex, ChatGPT, or another MCP client spend tokens reading CML's internal response schema. CML should do the local work of retrieval, filtering, trust labeling, compaction, and citation packaging before the outside model sees the context.

The intended shift is:

- current: raw source-shaped JSON -> outside model parses schema and decides how to use it
- target: compact CML packet -> outside model immediately reasons over selected memory and evidence

Token savings should come from:

- removing empty fields, internal metadata, repeated source schema, and raw score plumbing
- replacing broad source records with short summaries, selected quotes, citation handles, and trust/limit wording
- letting clients request expansion only for specific evidence they need

## Decision

Public V1 Bridge/MCP context calls must return model-ready context packets by default.

Raw JSON can remain available as a diagnostics/debug mode, but it should not be the default payload sent into an external model's context window or normal operator flow.

## Packet Shape

The default MCP context response should be a formatted text packet with a compact structured appendix only when needed.

Required sections:

1. `CML Context Packet`
2. `How To Use This Context`
3. `Answerable From Vault`
4. `Working Memory`
5. `Relevant Evidence`
6. `Citations`
7. `Trust And Limits`
8. `Expansion Handles`

The packet should explain:

- what the external model may answer from this packet
- which evidence is high confidence versus low trust
- whether the packet is complete or partial
- whether the query appears sensitive under personal-vault categories such as medical, legal, therapy, private correspondence, employment, identity, safety, finance, or credentials
- how to cite source handles
- how to request expansion for specific evidence
- what not to infer when evidence is weak or missing

## Raw JSON Policy

Raw JSON should be available only when explicitly requested:

- `format=json`
- `debug=true`
- developer CLI diagnostics
- internal regression tests

The default MCP tool response should be `format=packet` for context and `format=receipt` for capture flows.

## Implementation Scope Split

Do not implement this as one large cross-system refactor.

Pass 1 should fix the immediate MCP context problem only:

- change `backend/app/bridge_mcp.py`
- add packet formatting for `get_cluster_context`
- add `format=json` or `debug=true` opt-in for raw output
- include lightweight packet telemetry in the MCP text or metadata
- add focused tests in `backend/tests/test_bridge_mcp.py`

Pass 1 should not require changes to:

- `backend/app/api/routes/bridge.py`
- `backend/app/api/routes/chat.py`
- `backend/app/core/llm_runtime.py`
- database schema
- source chunking

Pass 2 must complete the deeper architecture:

- shared internal chat / Bridge packet builder
- expansion handles and expansion tools
- content-aware chunking for external artifacts and supported structured/code sources
- external response quality gating so bad outside-model answers do not become authoritative vault memory
- raw artifact reprocessing metadata or schema changes

Reason: internal chat and Bridge currently use different evidence shapes. Internal chat works from citation-shaped items; Bridge context currently returns source-record-shaped items. Forcing those into one shared builder before the MCP formatter exists would turn a clean Bridge fix into a larger routing/chat refactor.

## Structured Source Chunking Problem

`capture_external_artifact` currently stores external output as a normal source, then queues generic source reindexing. The same generic reindexing path is used for local files, synced folders, chat attachments, and other imported sources. The generic chunker in `backend/app/core/embeddings.py` uses:

- `CHUNK_SIZE_WORDS = 180`
- `CHUNK_OVERLAP_WORDS = 40`
- `text.split()` word windows

This is acceptable for prose but poor for code blocks, diffs, multi-file generated output, stack traces, logs, JSON/YAML/TOML, and markdown with headings.

Word-window chunking can cut through function signatures, code blocks, filenames, patch hunks, and structured records. That reduces retrieval quality and makes later cluster-expert training noisier.

## Content-Aware Chunking Decision

Pass 2 must replace generic word-window chunking with a content-aware chunk dispatcher for all relevant source indexing paths, not only Bridge captures.

Required strategies:

- Markdown: split by headings, fenced code blocks, and list/table boundaries.
- Code: split by file path, symbol/function/class boundaries where possible, and fenced block boundaries at minimum.
- Code parser fallback: if line/block heuristics do not preserve useful symbol boundaries for supported languages, Pass 2 must add parser-backed chunking using Tree-sitter or lightweight language-specific parsers before public V1 sign-off.
- Diff/patch: split by file and hunk.
- Logs/stack traces: split by event group, timestamp block, traceback, or error boundary.
- JSON/YAML/TOML: preserve valid object/section boundaries and store normalized structured payloads when possible.
- CSV/TSV: preserve headers and complete rows; split by row batches without cutting a row in half.
- Prose/transcripts: keep word/paragraph chunking, but preserve speaker turns and timestamps.

The indexing path should record a `content_profile` such as `prose`, `conversation`, `markdown`, `code`, `diff`, `log`, `structured_json`, `table_csv`, or `mixed_artifact`.

## External Response Quality Gate

`log_external_turn` currently stores whatever the external model returned as an `external_transcript` source. That is useful for audit/history, but unsafe as authoritative memory. If an outside model ignores CML context or hallucinates, the hallucination can be indexed, embedded, retrieved later, and eventually influence synthesis or expert training.

Pass 2 must add a Bridge writeback quality gate before external model responses become normal retrieval/training evidence.

Required captured metadata:

- `context_request_id`
- packet ID or packet hash
- evidence handles included in the packet
- evidence handles cited or referenced by the external model, when available
- client name and model name
- whether the response was expected to use CML context
- user-supplied artifact-vs-answer intent
- verifier status and verifier reasons

Required quality states:

- `grounded`: response is materially supported by the supplied CML packet
- `partially_grounded`: some claims are supported, but important claims are unsupported
- `ungrounded`: response does not use or contradicts the supplied CML context
- `unknown`: CML cannot determine grounding
- `user_artifact`: user intentionally saved an artifact, not an answer to be trusted as memory

Default policy:

- Store raw external turns for audit/history.
- Do not treat unverified external answers as trusted memory.
- Mark `ungrounded` and `unknown` external answers as low-trust or review-needed.
- Exclude `ungrounded` external answers from normal synthesis and cluster-expert training unless the user explicitly approves them.
- Allow `user_artifact` captures to remain searchable as artifacts, but do not promote them into distilled memory without review.

Verifier approach:

- First pass: deterministic checks for packet-handle citation, source-title overlap, quoted evidence overlap, and contradiction flags where available.
- Second pass: local LLM or extraction-based verifier when deterministic checks are insufficient.
- Always record verifier reasons so users and tests can inspect why a turn was accepted, downgraded, or quarantined.

## Pass 1 Implementation Plan

1. Add a `format` property to the `get_cluster_context` MCP tool schema with default `packet` and optional `json`.
2. Add a packet formatter in `backend/app/bridge_mcp.py` that consumes the existing Bridge context response shape.
3. Return formatted packet text by default from `call_get_cluster_context`.
4. Preserve raw `json.dumps(data, indent=2)` only when `format=json` or `debug=true` is requested.
5. Include basic telemetry in the packet:
   - raw JSON bytes
   - packet bytes
   - approximate savings percentage
   - source count
   - warning count
6. Keep `list_clusters` JSON-shaped for now; `log_external_turn` and `capture_external_artifact` may move to receipt-style summaries once quality-state visibility is ready.
7. Add unit tests in `backend/tests/test_bridge_mcp.py` with mocked `http_json`.
8. Add MCP smoke coverage proving default context output is packet text and raw JSON is opt-in.

## Pass 2 Implementation Plan

1. Decide the shared evidence model:
   - internal chat adopts a normalized Bridge/context-packet evidence shape, or
   - Bridge adopts citation-shaped evidence closer to internal chat
2. Add a shared context-packet builder only after the evidence model decision is made.
3. Add expansion handles and define the backend endpoints/tools they resolve to.
4. Add rate limits and permission checks for expansion calls.
5. Add content-profile detection for external captures.
6. Add content-aware chunk dispatch in the reindexing layer, driven by `source_type`, suffix/origin metadata, and detected content profile.
7. Add chunkers for code, diffs, logs, markdown, CSV/TSV, structured JSON/YAML/TOML, and transcripts.
8. Add parser-backed symbol chunking for supported code languages when heuristic line/block chunking fails retrieval/coherence tests. Prefer Tree-sitter where packaging is acceptable; otherwise use lightweight language-specific parsers for the highest-value languages.
9. Add external response quality metadata to Bridge turn capture and storage.
10. Add a verifier that classifies external responses as `grounded`, `partially_grounded`, `ungrounded`, `unknown`, or `user_artifact`.
11. Gate retrieval, distilled-memory extraction, and expert-training inclusion by external response quality state.
12. Add review/approval path for promoting ungrounded or unknown external answers into trusted memory.
13. Preserve or mark raw captured/imported content so re-chunking is possible after chunker upgrades.
14. Add tests proving code/diff/log/CSV/JSON/Markdown artifacts are not split only by word count.
15. Add tests proving ungrounded external answers are stored for audit but excluded from normal synthesis/training until approved.

## V1 Acceptance Criteria

- MCP `get_cluster_context` clients receive model-ready context packets by default.
- MCP capture tools return compact human-readable receipts by default, including quality state, trust tier, review-needed status, and reasons.
- MCP review queue tools let outside clients inspect pending downgraded captures and approve or keep them gated without dropping to raw HTTP.
- External models get explicit instructions for trust, citations, limits, and expansion.
- Raw JSON remains available only as an explicit diagnostics/debug format.
- Bridge packet telemetry proves size reduction versus raw API JSON.
- Captured code/diff/log/structured artifacts are chunked on semantic boundaries where practical.
- Supported code/structured local files are chunked on semantic boundaries where practical.
- Supported code files use parser-backed symbol chunking when heuristics cannot preserve coherent function/class/module units.
- Captured artifacts can be reprocessed when chunking rules improve.
- External model responses are quality-gated before becoming authoritative retrieval, distilled-memory, or expert-training evidence.
- Ungrounded or unknown external answers are stored for audit/history but excluded from normal synthesis and expert training unless explicitly approved.
