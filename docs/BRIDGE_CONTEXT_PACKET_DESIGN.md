# Bridge Context Packet Design

Last updated: 2026-06-26

## Current Status

This design is now implemented for current V1 backend scope.

What is complete in the repo:

- MCP `get_cluster_context` defaults to model-readable packet text instead of raw JSON.
- Raw JSON is opt-in through `format=json` or debug paths.
- Bridge and MCP now route through the shared retrieval-grounded cluster bundle builder instead of assembling expert/context fields independently.
- Bridge capture tools default to human-readable receipts.
- Shared packet helpers now exist in `backend/app/core/context_packets.py` and are used by both Bridge and internal grounded-chat paths.
- Expansion handles and MCP/HTTP expansion flows exist.
- Bundle metadata now reaches packet consumers:
  - `expert_digest`
  - `retrieval_authority`
  - `token_ledger`
  - `bundle_status`
- MCP review queue tools now exist for downgraded writebacks:
  - `list_writeback_reviews`
  - `decide_writeback_review`
  - `list_captures`
- Bridge writeback quality states exist and are enforced in normal retrieval/memory/training paths:
  - `grounded`
  - `partially_grounded`
  - `ungrounded`
  - `unknown`
  - `user_artifact`
- Bridge and chat packet telemetry now records raw-vs-packet size reduction.
- Content-aware chunking is no longer prose-only generic word windows for all source types.

Primary implementation points:

- `backend/app/bridge_mcp.py`
- `backend/app/api/routes/bridge.py`
- `backend/app/core/context_packets.py`
- `backend/app/core/context_memory.py`
- `backend/app/core/embeddings.py`
- `backend/tests/test_bridge_mcp.py`
- `backend/tests/test_source_pages.py`
- `backend/tests/test_parameters_doc_cases.py`

## What Was Delivered

### Packet Formatting

Completed:

- `get_cluster_context` uses `format=packet` by default.
- Packet text includes the intended user/model sections:
  - `CML Context Packet`
  - `How To Use This Context`
  - `Answerable From Vault`
  - `Working Memory`
  - `Relevant Evidence`
  - `Citations`
  - `Trust And Limits`
  - `Expansion Handles`
  - `Cluster Profile`
  - `Authority`
  - `Token Savings`
- Packet telemetry includes:
  - raw JSON bytes
  - packet bytes
  - savings percentage

### Shared Packet Builder

Completed:

- Bridge and grounded chat now share the same packet-rendering layer in `backend/app/core/context_packets.py`.
- Bridge uses `build_bridge_context_packet(...)`.
- Grounded chat uses `build_chat_context_packet(...)`.
- The shared renderer gives both paths the same instruction framing, trust wording, evidence presentation, and expansion-handle surface.
- Packet rendering now carries the bundle-era contract explicitly:
  - retrieval remains the authority for facts and citations
  - expert digest is compression only
  - token savings are visible to the caller

### Expansion

Completed:

- Expansion handles are emitted in packets.
- Bridge exposes expansion through:
  - MCP `expand_context_item`
  - HTTP `/api/v1/bridge/context/expand`
- Tests and Bridge smoke cover the expansion path.

### External Response Quality Gate

Completed:

- External-turn and artifact writeback now capture quality state and reasons.
- Ungrounded and partially grounded external answers stay review-gated instead of silently becoming trusted memory.
- Review queue listing, approval, and capture listing are available through MCP and HTTP flows.
- Retrieval, memory extraction, and expert-training inclusion are gated by external quality state.

### Content-Aware Chunking

Completed for current scope:

- `source_chunks` now store `content_profile`, `chunk_strategy`, and `chunk_meta_json`.
- Content-aware chunk dispatch exists for:
  - conversation/transcripts
  - Markdown
  - code
  - diffs
  - logs
  - structured JSON/YAML/TOML-style content
  - CSV/TSV
- Parser-backed or structure-aware code chunking now exists for:
  - Python via AST symbol extraction
  - JS/TS/TSX/JSX, Go, Java, C#, C/C++, and Rust via brace/symbol block chunking

## Design Intent That Remains Relevant

The original problem statement still stands:

- Bridge should send compact, model-usable context rather than source-shaped raw API JSON.
- Context reduction should come from local evidence shaping and reversible expansion, not from forcing external models to parse CML schema.
- External model outputs must not become authoritative memory without grounding checks.
- Expert compression is optional and must never become citation authority.

## Bundle Contract

The current packet contract is a retrieval-grounded context bundle, not a standalone model response.

Current packet/API bundle fields:

- `expert_digest`
- `expert_used`
- `expert_mode`
- `retrieval_authority`
- `token_ledger`
- `bundle_status`
- `expansion_handles`

Authority rules:

- Facts and citations come from retrieved evidence.
- Expert digest is a non-authoritative compression layer only.
- Expansion handles must always resolve back to source, chunk, or page evidence.

## Remaining Gaps

This document should not claim that every stretch goal is finished.

Still open or still needing broader proof:

- Broader real-vault eval coverage for packet usefulness and expansion usefulness.
- More mixed-artifact retrieval/chunking evaluation on real user-owned data.
- Stronger proof breadth for external-client/browser flows beyond the current HTTP/MCP/live-extension smokes.
- If heuristic symbol chunking proves insufficient on high-value languages, a stronger parser layer may still be justified later. Current code already has parser-backed Python support plus structure-aware chunkers for several brace languages, so this is no longer a blocker for current scope.
- Re-chunking/reprocessing policy should stay explicit as chunking rules evolve, but the core packet and writeback architecture is no longer blocked on it.

## Acceptance Status

### Completed For Current Scope

- MCP context defaults to packet text.
- Raw JSON is diagnostics-only by explicit request.
- Capture tools return compact receipts by default.
- Review queue tools exist for downgraded captures.
- Expansion handles and expansion tools exist.
- Shared Bridge/chat packet rendering exists.
- Shared Bridge/chat bundle rendering exists with expert digest, authority, token-ledger, and bundle-status fields.
- Packet telemetry exists.
- External response quality gating exists.
- Content-aware chunking exists across the main supported structured source classes.

### Still Release-Proof Work, Not Missing Architecture

- Larger real-vault context-layer recall and packet-savings proof.
- Expansion usefulness proof on broader real usage.
- More mixed-artifact chunking/retrieval eval breadth.
- Clean external-client/browser validation breadth on release-like environments.
