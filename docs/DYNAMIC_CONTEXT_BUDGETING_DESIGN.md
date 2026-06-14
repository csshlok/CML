# Dynamic Context Budgeting Design

Last updated: 2026-06-14

## Current Status

This design is implemented in backend code for current scope.

Primary implementation points:

- `backend/app/core/context_budget_policy.py`
- `backend/app/api/routes/chat.py`
- `backend/tests/test_source_pages.py`

Implemented behavior:

- context budget now scales by hardware tier
- context budget now scales by active chat-model tier
- context budget now adapts by query type
- context budget now adapts by trust mode
- busy/degraded runtime states can narrow the budget
- chat coverage metadata now records the selected budget policy fields

This is no longer a doc-only design.

## Problem It Solved

The previous static approach was too blunt:

- one global `llm_context_token_budget` default of `1200`
- early hard caps on evidence selection
- no meaningful distinction between low-tier and high-tier hardware/model setups

That was inconsistent with the product’s hardware-aware runtime story and underfed stronger local model paths.

## What The Repo Now Does

### Selector Module

`select_context_budget(...)` now exists in `backend/app/core/context_budget_policy.py`.

It currently uses:

- hardware tier
- active chat model tier
- prompt/query type
- expanded-analysis state
- trust gate state
- runtime state
- candidate citation count
- cluster count used

### Current Hardware Base Budgets

Implemented:

- `unsupported`: `1200`
- `unknown`: `1200`
- `cpu_minimum_spec`: `1600`
- `cpu_high_spec`: `2800`
- `gpu_or_high_spec_candidate`: `4200`

### Current Model Multipliers

Implemented:

- `small`: `1.0x`
- `standard`: `1.0x`
- `quality`: `1.35x`
- `large`: `1.5x`

### Current Query Multipliers

Implemented:

- `general`: `0.75x`
- `fact_lookup`: `0.9x`
- `compare_synthesis`: `1.1x`
- `plan_multistep`: `1.25x`
- `expanded_analysis`: `1.5x`

### Current Trust Multipliers

Implemented:

- `trusted`: `1.0x`
- `mixed`: `0.85x`
- `low_trust_heavy`: `0.65x`

### Runtime-Aware Narrowing

Implemented:

- `busy` runtime narrows the selected budget
- degraded/non-ready runtime narrows it further

### Floor And Ceiling

Implemented:

- floor remains tied to `llm_context_token_budget`, with a hard minimum of `1200`
- ceiling is capped at `8000`

## Telemetry Now Recorded

The chat coverage ledger now records dynamic-budget metadata such as:

- `budget_token_budget`
- `budget_floor_budget`
- `budget_hardware_tier`
- `budget_model_tier`
- `budget_query_type`
- `budget_trust_mode`
- `budget_widening_applied`
- `budget_narrowing_applied`
- `budget_widening_reason`
- `budget_narrowing_reason`

This satisfies the core observability requirement from the original design.

## What Changed Relative To The Original Design

The original design called for a two-stage policy:

1. `select_context_budget(...)`
2. `allocate_context_budget(...)`

Current repo state:

- Stage 1 is implemented.
- The allocator behavior is partially reflected in the grounded chat route and evidence-selection flow.
- The design’s broader “full allocator over all evidence classes” intent is only partially realized.

So the honest status is:

- dynamic budget selection: complete for current scope
- allocator sophistication: partially complete
- eval/UI proof breadth: still open

## Verification

Current focused regression coverage includes:

- dynamic budget widens for a quality model on high-spec hardware
- coverage ledger exposes budget hardware/model/query metadata
- grounded chat passes the selected budget metadata through the current path

Primary references:

- `backend/tests/test_source_pages.py`
- `backend/app/api/routes/chat.py`

## Remaining Work

Not missing architecture, but still open:

- broader real-vault budget-quality proof
- latency/quality evaluation across more hardware tiers and model tiers
- deeper allocator improvements for evidence-width and citation-allocation behavior
- richer diagnostics/UI surfacing of why a budget was chosen
- reuse of the same selector/allocation policy as the standard policy for every shared context-packet path

## Acceptance Status

### Completed For Current Scope

- static single-ceiling behavior is no longer the only policy
- higher-tier hardware/model paths can widen the budget
- lower-trust or degraded-runtime cases can narrow the budget
- selected budget metadata is observable in coverage telemetry

### Still Open As Release-Proof Work

- broader real-vault answer-quality validation
- stronger allocator/evidence-packet proof on larger mixed corpora
- clearer UI/diagnostics presentation of budget selection outcomes
