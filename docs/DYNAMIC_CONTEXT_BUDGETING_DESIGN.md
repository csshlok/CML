# Dynamic Context Budgeting Design

Last updated: 2026-06-13

## Problem

Current chat synthesis budgeting is intentionally conservative but too static:

- one global `llm_context_token_budget` default of `1200`
- snippets are pre-trimmed before budget selection
- citations are capped too early
- the same effective ceiling applies across low-tier and high-tier machines
- the same ceiling applies across 4B and 8B model paths

This creates three product problems:

1. Higher-quality model options are underfed and do not benefit enough from their larger usable context.
2. Evidence shaping is determined by early hard caps instead of an explicit allocation policy.
3. Token management is not aligned with the product's hardware-aware runtime story.

## Goal

Replace the single static evidence ceiling with a dynamic budget policy that:

- scales by hardware tier
- scales by active chat-model tier
- adapts by query type
- adapts by trust mode
- leaves explicit safety margin for prompt, system instructions, and answer generation
- records what budget was chosen and how it was used

This design applies to internal chat first and should later become the default budget policy for shared context packets.

## Non-Goals

- Do not use the full raw model context window.
- Do not widen context without preserving latency guardrails.
- Do not bypass trust gating just because more context is available.
- Do not keep the current fixed citation-count and snippet-length caps as the main control surface.

## Design Summary

Budgeting becomes a two-stage policy:

1. `select_context_budget(...)`
   Chooses an evidence budget from runtime and query signals.
2. `allocate_context_budget(...)`
   Spends that budget across citations, summaries, and evidence snippets.

The old global default becomes only a floor / fallback, not the normal final budget.

## Inputs

The budget selector should consume:

- `hardware_tier`
  - `unsupported`
  - `unknown`
  - `cpu_minimum_spec`
  - `cpu_high_spec`
  - `gpu_or_high_spec_candidate`
- `active_chat_model`
  - default 4B
  - low-spec fallback 4B-class
  - quality 8B
  - later larger accepted models
- `runtime_state`
  - ready
  - busy
  - degraded
- `query_type`
  - direct / general
  - fact lookup
  - compare / synthesis
  - plan / multi-step
  - expanded analysis
- `trust_mode`
  - trusted
  - mixed
  - low-trust-heavy
- `cluster_count_used`
- `candidate_citation_count`
- `expanded_analysis`

## Stage 1: Budget Selection

### Base budget by hardware tier

Suggested first-pass ranges:

- `unsupported` or `unknown`: `1200`
- `cpu_minimum_spec`: `1600`
- `cpu_high_spec`: `2800`
- `gpu_or_high_spec_candidate`: `4200`

### Model multiplier

Suggested first-pass adjustments:

- 4B-class chat model: `1.0x`
- 8B-class chat model: `1.35x`
- larger approved chat model: `1.5x`

### Query multiplier

Suggested first-pass adjustments:

- direct / general: `0.75x`
- fact lookup: `0.9x`
- compare / synthesis: `1.1x`
- plan / multi-step: `1.25x`
- expanded analysis: `1.5x`

### Trust adjustment

Suggested first-pass adjustments:

- trusted evidence set: no reduction
- mixed-trust evidence: `0.85x`
- low-trust-heavy evidence: `0.65x` and prefer extract/degrade path

### Hard floor and ceiling

- minimum final evidence budget: `1200`
- first-pass maximum final evidence budget: `8000`

Rationale:

- `1200` preserves the current conservative fallback path.
- `8000` is wide enough to materially improve quality on stronger setups without consuming the whole model window.

### Safety reserve

Reserve a separate share of the model window for:

- system prompt
- user prompt
- routing/cluster labels
- answer generation
- response-time and truncation safety

The evidence budget should be the amount left after reserve, not the entire prompt budget.

## Stage 2: Budget Allocation

The allocator should operate on full candidate evidence before hard truncation.

### Remove early fixed caps

Replace:

- fixed `results[:4]`
- fixed `420`-char default snippet trim

With:

- citation count selected from budget
- snippet size selected from budget
- content-type-aware shaping before final trim

### Suggested allocation policy

1. Estimate prompt + metadata cost.
2. Reserve budget for:
   - cluster labels
   - distilled memory / working memory
   - warnings / trust notes
3. Use remaining budget for evidence.
4. Allocate evidence budget in descending priority:
   - diverse top-ranked citations
   - contradiction-supporting citations when conflict is detected
   - wider excerpts only when budget remains

### Citation-count guidance

Suggested starting policy:

- low budget: `3-4` citations
- medium budget: `5-8` citations
- high budget: `8-12` citations
- expanded analysis: `10-16` evidence items, some may be compressed summaries rather than raw snippets

### Snippet-width guidance

Suggested starting policy:

- low budget: short evidence snippets
- medium budget: standard snippet windows
- high budget: larger snippet windows or paired evidence windows
- table/JSON/code/log payloads should use content-type-aware shaping, not plain prose truncation

## Content-Type-Aware Allocation

Budget allocation should not flatten all evidence into prose.

Required content classes:

- prose
- code
- logs
- tables / JSON
- transcript history

Examples:

- code: keep fewer but structurally larger spans
- logs: keep error clusters and timestamps, not broad raw log walls
- tables / JSON: compact into schema-aware summary plus expansion handle
- transcript history: compact into turn summaries first, expand only if needed

## Runtime-Aware Degradation Rules

Budget selection should narrow automatically when:

- runtime is busy
- runtime latency exceeds threshold
- memory pressure is high
- trust mode is low-trust-heavy

This means the policy remains dynamic in both directions:

- widen on stronger setups
- shrink when local conditions are poor

## Telemetry

Record for each generation:

- selected budget
- hardware tier
- model tier
- query type
- trust mode
- prompt token estimate
- evidence token estimate
- citation count selected
- citation count trimmed
- snippet tokens before trim
- snippet tokens after trim
- whether dynamic widening was applied
- whether dynamic narrowing was applied

Store these in the existing retrieval / coverage reporting path where possible.

## UI / Diagnostics

Expose in diagnostics and later UI:

- why this budget was chosen
- what limited it
- whether a higher-capacity machine/model path would have widened it
- how much evidence was excluded

This is important because the product promises hardware-aware model recommendations. Evidence budgeting should reflect that same logic.

## Implementation Plan

### Backend

1. Add new module:
   - `backend/app/core/context_budget_policy.py`
2. Move budget selection logic out of route-local constant usage.
3. Add runtime/model-tier helpers for chat model classes.
4. Replace early fixed citation/snippet caps in `chat.py` with allocator-driven selection.
5. Extend coverage ledger fields for dynamic-budget metadata.
6. Reuse the same selector later for shared context packets.

### Config

Keep `llm_context_token_budget` only as:

- fallback minimum
- test override
- operator emergency override

Add optional policy knobs:

- per-tier base budgets
- max evidence budget
- busy-runtime penalty
- expanded-analysis multiplier

### Tests

Add coverage for:

- low-tier vs high-tier budget selection
- 4B vs 8B budget widening
- fact lookup vs synthesis vs expanded analysis
- trusted vs low-trust-heavy evidence
- allocator choosing more citations when budget allows
- allocator widening snippets when budget allows
- regression that large models are no longer stuck at the same fixed evidence ceiling

### Evals

Measure:

- answer quality lift from wider dynamic budgets
- latency delta by tier
- token usage by tier
- contradiction handling under wider evidence windows
- whether higher-tier models actually benefit from wider evidence packets

## Release Gate

Do not keep the current static ceiling as the public V1 behavior if:

- the product still markets hardware-aware model tiers
- the product still markets a quality model option
- the product still claims to be an intelligent context-management layer

Public V1 should ship with dynamic evidence budgeting or explicitly downgrade any hardware-aware / higher-quality model positioning.
